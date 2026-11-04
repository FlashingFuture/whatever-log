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
import logging
import re
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from contextlib import closing
from pathlib import Path

from chromium.browsers import BROWSERS
from chromium.profiles import profile_folders
from chromium.snapshot import (
    create_work_dir,
    open_readonly,
    remove_work_dir,
    snapshot_database,
)

from hub.memory_cache import ImageMemoryCache

logger = logging.getLogger("hub")

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
# icon_mapping을 favicon_bitmaps에 조인하면 같은 아이콘을 쓰는 페이지 수만큼 BLOB 행이 반복돼서
# (방문 페이지가 많은 도메인이면 수천 번) 메모리와 시간이 낭비된다 — 아이콘 id만 먼저 구해
# 비트맵 행은 한 번씩만 읽는다.
_FAVICON_QUERY = (
    "SELECT b.image_data, b.width, b.last_updated "
    "FROM favicon_bitmaps b "
    "WHERE b.icon_id IN (SELECT m.icon_id FROM icon_mapping m WHERE "
    + " OR ".join(["m.page_url LIKE ?"] * _PAGE_URL_PATTERN_COUNT)
    + ")"
)

# 서로 다른 도메인의 캐시 미스가 동시에 여러 개 오면 각자 모든 프로필의 Favicons를 복사한다 —
# 임시 디스크 사용과 지연이 요청 수에 비례해 커지지 않게 동시에 복사하는 수를 제한한다.
_MAX_CONCURRENT_READS = 2


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


# (순위 키, PNG). 키가 작을수록 좋다: 선호 크기에 가까운 것, 같으면 최근에 갱신된 것.
_Candidate = tuple[tuple[int, int], bytes]


def _best_candidate(rows: Iterable[tuple[bytes | None, int | None, int | None]]) -> _Candidate | None:
    """(PNG, 너비, 갱신 시각) 행들에서 가장 좋은 후보 하나. 행을 한 줄씩 훑어 최선만 들고 있는다.

    같은 아이콘을 쓰는 페이지가 많거나 비트맵이 큰 프로필에서도 행 전체를 메모리에 올리지
    않는다. Chromium 스키마는 세 컬럼 모두 NULL을 허용한다 — NULL이 있는 행이나 PNG가 아닌
    데이터는 후보에서 뺀다(비교하다 예외가 나면 응답 없이 연결이 끊긴다).
    """
    best: _Candidate | None = None
    for data, width, updated in rows:
        if data is None or width is None or updated is None or bytes(data[:8]) != _PNG_MAGIC:
            continue
        rank = (abs(width - _PREFERRED_WIDTH), -updated)
        if best is None or rank < best[0]:
            best = (rank, bytes(data))
    return best


def _pick_best(rows: Iterable[tuple[bytes | None, int | None, int | None]]) -> bytes | None:
    """_best_candidate의 PNG만."""
    best = _best_candidate(rows)
    return None if best is None else best[1]


class TransientReadError(Exception):
    """브라우저 파일을 읽지 못했다 — 복사 실패, 임시 폴더를 못 만듦, 깨진 파일 등.

    "아이콘이 없다"(읽었는데 없음)와 다르다. 이 경우를 없음으로 기억하면 브라우저 파일이 곧 복구돼도
    그 도메인이 한동안(없음 기억 시간) 계속 404가 된다 — 그래서 기억하지 않고 다음 요청에서 다시
    시도한다.
    """


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
        self._read_slots = threading.BoundedSemaphore(_MAX_CONCURRENT_READS)
        # 지우지 못한 임시 복사본 폴더. 다음 복사 때 다시 지워 본다(방문 주소가 들어 있다).
        self._leftover_dirs: list[Path] = []
        self._leftover_guard = threading.Lock()

    def get(self, domain: str) -> tuple[str, bytes] | None:
        """(ETag로 쓸 키, PNG 바이트). 도메인 모양이 틀렸거나 브라우저에 아이콘이 없으면 None."""
        if not is_valid_domain(domain):
            return None
        # 같은 도메인의 동시 요청이 각자 파일을 복사하지 않게 캐시가 한 번만 읽게 한다. 읽는 데
        # 실패한 경우(TransientReadError 등)는 캐시가 아무것도 기억하지 않고 예외를 돌려주므로,
        # 여기서 "없음"으로 응답하되 다음 요청에서 다시 시도한다. 아이콘은 장식이라 브라우저 파일이
        # 이상해도 API 전체 오류가 되면 안 된다.
        try:
            png = self._cache.get_or_load(domain, lambda: self._read_slot(domain))
        except Exception:
            return None
        if png is None:
            return None
        # 키는 내용의 해시라, 브라우저가 아이콘을 바꾸면 브라우저 캐시도 자연히 새로 받는다.
        return hashlib.sha256(png).hexdigest()[:32], png

    def _read_slot(self, domain: str) -> bytes | None:
        # 서로 다른 도메인의 동시 복사 수를 제한한다.
        with self._read_slots:
            return self._read_from_browsers(domain)

    def _read_from_browsers(self, domain: str) -> bytes | None:
        """모든 브라우저·프로필에서 가장 좋은 아이콘. 읽었는데 없으면 None, 읽지 못한 곳이 있고
        찾은 것도 없으면 TransientReadError(없음으로 기억하면 안 된다).

        프로필마다 따로 실패한다 — 한 프로필이 깨졌다고 다른 프로필의 아이콘을 못 찾으면 안 된다.
        """
        patterns = _page_url_patterns(domain)
        best: _Candidate | None = None
        failed = False
        for user_data_dir in self._user_data_dirs:
            for folder in profile_folders(user_data_dir):
                try:
                    found = self._query_profile(user_data_dir / folder / "Favicons", patterns)
                except Exception:
                    failed = True
                    continue
                if found is not None and (best is None or found[0] < best[0]):
                    best = found
        if best is not None:
            return best[1]
        if failed:
            raise TransientReadError(domain)
        return None

    def _query_profile(self, source: Path, patterns: list[str]) -> _Candidate | None:
        """한 프로필의 최선 후보. 아이콘 저장소 파일이 없는 프로필은 None(실패가 아니다)."""
        if not source.exists():
            return None
        self._retry_leftover_dirs()
        # 이 폴더는 방문 사이트 정보를 담은 복사본이라 쓰고 나면 바로 지운다.
        work_dir = create_work_dir(WORK_DIR_PREFIX)
        try:
            copy = work_dir / "Favicons"
            if not snapshot_database(source, copy):
                raise TransientReadError(source.parent.name)
            try:
                with closing(open_readonly(copy)) as db:
                    # 커서를 한 줄씩 읽는다(_best_candidate) — fetchall로 모으지 않는다.
                    return _best_candidate(db.execute(_FAVICON_QUERY, patterns))
            except sqlite3.Error as error:
                raise TransientReadError(source.parent.name) from error
        finally:
            self._discard_work_dir(work_dir)

    def _discard_work_dir(self, work_dir: Path) -> None:
        """복사본 폴더를 지운다. 못 지우면 경고(도메인이나 방문 주소는 적지 않는다)를 남기고
        기억해 두었다가 다음 복사 때 다시 지워 본다."""
        if remove_work_dir(work_dir):
            return
        logger.warning("사이트 아이콘 임시 복사본을 지우지 못했습니다(나중에 다시 시도합니다): %s", work_dir)
        with self._leftover_guard:
            self._leftover_dirs.append(work_dir)

    def _retry_leftover_dirs(self) -> None:
        with self._leftover_guard:
            pending, self._leftover_dirs = self._leftover_dirs, []
        for work_dir in pending:
            if not remove_work_dir(work_dir):
                with self._leftover_guard:
                    self._leftover_dirs.append(work_dir)
