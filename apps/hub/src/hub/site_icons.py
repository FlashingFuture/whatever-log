"""사이트(도메인)의 아이콘(favicon)을 브라우저가 이미 저장해 둔 것에서 읽어 돌려준다.

Chromium 계열 브라우저(Chrome, Edge, Brave, Vivaldi)는 방문한 사이트의 아이콘을 프로필의
`Favicons`(SQLite)에 PNG로 보관한다. 설치된 브라우저들의 프로필을 모두 찾아, 선호 크기에
가장 가깝고 가장 최근에 갱신된 것을 쓴다. 그걸 읽으면 사이트로 요청을 보낼 필요가 없다 — 외부
네트워크 요청이 0건이라 방문 사실이 새지 않는다(docs/data-handling.md). 이 모듈은 파일을 읽기만
하고, 원본은 건드리지 않는다.

브라우저가 파일을 쓰는 중이므로 원본을 열지 않고, 캐시에 없을 때마다 일관된 복사본을
임시 작업 폴더에 만들어(chromium.snapshot) 읽은 뒤 바로 지운다(파일이 작아 비용이 미미하다).
결과는 디스크에 저장하지 않고 메모리에만 두며, 일정 시간이 지나면 버린다(SITE_ICON_TTL_SECONDS)
— 사용자가 브라우저 기록을 지우거나 아이콘이 바뀌면 그 시간 안에 반영된다. 못 찾은 도메인은
잠시 "없음"으로 기억해 같은 요청마다 파일을 복사하지 않고, 같은 도메인의 동시 요청은 한 번만
조회한다(hub.memory_cache).
"""

import hashlib
import re
import shutil
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from chromium.browsers import BROWSERS
from chromium.profiles import profile_folders
from chromium.snapshot import create_work_dir, snapshot_database

from hub.memory_cache import ImageMemoryCache

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PREFERRED_WIDTH = 32  # 화면에 ~20px로 쓰니 16px은 흐리고 큰 것은 낭비라, 32px 쪽을 고른다.

# 메모리에 둔 아이콘을 버리는 시간. 브라우저 쪽 캐시(Cache-Control max-age)도 같은 값을 써서
# 기록을 지운 뒤에 이 시간보다 오래 남지 않게 한다.
SITE_ICON_TTL_SECONDS = 10 * 60

# 임시 작업 폴더 이름의 앞부분. hub가 시작할 때 이 이름으로 남은 폴더를 지운다.
WORK_DIR_PREFIX = "whatever-log-favicons-"

# hub가 받아 주는 도메인의 모양. LIKE 패턴에 쓰이므로 특수 문자가 들어가는 걸 미리 막는다.
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")

# 도메인 하나의 페이지 주소를 찾는 LIKE 패턴 수: (https, http) x (도메인, www.도메인) x (경로 "/",
# 포트 ":"). 쿼리 문자열을 상수로 만들어 두려고 개수를 미리 정해 둔다.
_PAGE_URL_PATTERN_COUNT = 8
_FAVICON_QUERY = (
    "SELECT b.image_data, b.width, b.last_updated "
    "FROM icon_mapping m JOIN favicon_bitmaps b ON b.icon_id = m.icon_id "
    "WHERE " + " OR ".join(["m.page_url LIKE ?"] * _PAGE_URL_PATTERN_COUNT)
)


def is_valid_domain(domain: str) -> bool:
    """도메인으로 쓸 수 있는 모양인지(소문자 영숫자·점·하이픈, 253자 이하)."""
    return _DOMAIN.fullmatch(domain) is not None


def _page_url_patterns(domain: str) -> list[str]:
    """브라우저의 icon_mapping.page_url에서 이 도메인의 페이지를 찾는 LIKE 패턴들.

    도메인 뒤에 "/"(경로)나 ":"(포트, 예: localhost:3000)가 오는 주소를 모두 잡는다 —
    기록할 때(domain_of) 포트를 버리므로 포트가 있는 페이지도 같은 도메인이다.
    """
    patterns = [
        f"{scheme}://{host}{end}"
        for scheme in ("https", "http")
        for host in (domain, f"www.{domain}")
        for end in ("/%", ":%")
    ]
    assert len(patterns) == _PAGE_URL_PATTERN_COUNT
    return patterns


def _pick_best(rows: list[tuple[bytes | None, int | None, int | None]]) -> bytes | None:
    """(PNG, 너비, 갱신 시각) 후보 중 선호 크기에 가장 가깝고 최근에 갱신된 것.

    Chromium 스키마는 세 컬럼 모두 NULL을 허용한다 — NULL이 있는 행이나 PNG가 아닌 데이터는
    후보에서 뺀다(비교하다 예외가 나면 응답 없이 연결이 끊긴다).
    """
    candidates = [
        (data, width, updated)
        for data, width, updated in rows
        if data is not None
        and width is not None
        and updated is not None
        and bytes(data[:8]) == _PNG_MAGIC
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda row: (abs(row[1] - _PREFERRED_WIDTH), -row[2]))
    return bytes(best[0])


class SiteIconStore:
    """도메인 → 아이콘 PNG. 브라우저들의 Favicons에서 읽고 메모리에 캐시한다."""

    def __init__(
        self,
        user_data_dirs: Sequence[Path] | None = None,
        cache: ImageMemoryCache | None = None,
    ) -> None:
        self._user_data_dirs = (
            list(user_data_dirs)
            if user_data_dirs is not None
            else [browser.user_data_dir() for browser in BROWSERS]
        )
        self._cache = cache or ImageMemoryCache(ttl_seconds=SITE_ICON_TTL_SECONDS)

    def get(self, domain: str) -> tuple[str, bytes] | None:
        """(ETag로 쓸 키, PNG 바이트). 도메인 모양이 틀렸거나 브라우저에 아이콘이 없으면 None."""
        if not is_valid_domain(domain):
            return None
        png = self._cache.get(domain)
        if png is None:
            if self._cache.is_missing(domain):
                return None
            # 같은 도메인의 동시 요청이 각자 파일을 복사하지 않게, 잠근 뒤 다시 확인한다.
            with self._cache.lock_for(domain):
                png = self._cache.get(domain)
                if png is None:
                    if self._cache.is_missing(domain):
                        return None
                    png = self._safe_read(domain)
                    if png is None:
                        self._cache.mark_missing(domain)
                        return None
                    self._cache.put(domain, png)
        # 키는 내용의 해시라, 브라우저가 아이콘을 바꾸면 브라우저 캐시도 자연히 새로 받는다.
        return hashlib.sha256(png).hexdigest()[:32], png

    def _safe_read(self, domain: str) -> bytes | None:
        try:
            return self._read_from_browsers(domain)
        except Exception:
            # 아이콘은 장식이라, 브라우저 파일이 이상해도 API 전체 오류가 되면 안 된다.
            return None

    def _read_from_browsers(self, domain: str) -> bytes | None:
        patterns = _page_url_patterns(domain)
        rows: list[tuple[bytes | None, int | None, int | None]] = []
        for user_data_dir in self._user_data_dirs:
            for folder in profile_folders(user_data_dir):
                rows.extend(self._query_profile(user_data_dir / folder / "Favicons", patterns))
        return _pick_best(rows)

    def _query_profile(
        self, source: Path, patterns: list[str]
    ) -> list[tuple[bytes | None, int | None, int | None]]:
        # 이 폴더는 방문 사이트 정보를 담은 복사본이라 쓰고 나면 바로 지운다.
        work_dir = create_work_dir(WORK_DIR_PREFIX)
        try:
            copy = work_dir / "Favicons"
            if not snapshot_database(source, copy):
                return []
            try:
                with closing(sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)) as db:
                    return db.execute(_FAVICON_QUERY, patterns).fetchall()
            except sqlite3.Error:
                return []
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
