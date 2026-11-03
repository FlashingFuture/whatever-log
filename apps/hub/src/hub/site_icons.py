"""사이트(도메인)의 아이콘(favicon)을 브라우저가 이미 저장해 둔 것에서 읽어 돌려준다.

Chromium 계열 브라우저(Chrome, Edge, Brave, Vivaldi)는 방문한 사이트의 아이콘을 프로필의
`Favicons`(SQLite)에 PNG로 보관한다. 설치된 브라우저들의 프로필을 모두 찾아, 선호 크기에
가장 가깝고 가장 최근에 갱신된 것을 쓴다. 그걸 읽으면
사이트로 요청을 보낼 필요가 없다 — 외부 네트워크 요청이 0건이라 방문 사실이 새지 않는다
(docs/data-handling.md). 이 모듈은 파일을 읽기만 하고, 원본은 건드리지 않는다.

브라우저가 파일을 잠가 두므로 원본을 열지 않고, 요청마다 임시 폴더에 복사해서 읽은 뒤 바로
지운다(파일이 작아 비용이 미미하다). 결과는 디스크에 저장하지 않고 메모리에만 둔다 — 사용자가
브라우저 기록을 지웠는데 사이트 흔적이 hub 쪽에 남지 않게 하려는 것이다. 못 찾은 도메인은
잠시 "없음"으로 기억해 같은 요청마다 파일을 복사하지 않는다.
"""

import hashlib
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path

from chromium.browsers import BROWSERS
from chromium.profiles import profile_folders

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PREFERRED_WIDTH = 32  # 화면에 ~20px로 쓰니 16px은 흐리고 큰 것은 낭비라, 32px 쪽을 고른다.
_NEGATIVE_TTL_SECONDS = 300.0
_MEMORY_ENTRIES = 256

# hub가 받아 주는 도메인의 모양. LIKE 패턴에 쓰이므로 특수 문자가 들어가는 걸 미리 막는다.
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")


def is_valid_domain(domain: str) -> bool:
    """도메인으로 쓸 수 있는 모양인지(소문자 영숫자·점·하이픈, 253자 이하)."""
    return _DOMAIN.fullmatch(domain) is not None


def _page_url_patterns(domain: str) -> list[str]:
    """Chrome의 icon_mapping.page_url에서 이 도메인의 페이지를 찾는 LIKE 패턴들."""
    return [f"{scheme}://{host}/%" for scheme in ("https", "http") for host in (domain, f"www.{domain}")]


def _pick_best(rows: list[tuple[bytes, int, int]]) -> bytes | None:
    """(PNG, 너비, 갱신 시각) 후보 중 선호 크기에 가장 가깝고 최근에 갱신된 것."""
    candidates = [row for row in rows if bytes(row[0][:8]) == _PNG_MAGIC]
    if not candidates:
        return None
    best = min(candidates, key=lambda row: (abs(row[1] - _PREFERRED_WIDTH), -row[2]))
    return bytes(best[0])


class SiteIconStore:
    """도메인 → 아이콘 PNG. 브라우저들의 Favicons에서 읽고 메모리에 캐시한다."""

    def __init__(self, user_data_dirs: Sequence[Path] | None = None) -> None:
        self._user_data_dirs = (
            list(user_data_dirs)
            if user_data_dirs is not None
            else [browser.user_data_dir() for browser in BROWSERS]
        )
        self._memory: OrderedDict[str, bytes] = OrderedDict()
        self._missing_until: dict[str, float] = {}
        self._guard = threading.Lock()

    def get(self, domain: str) -> tuple[str, bytes] | None:
        """(ETag로 쓸 키, PNG 바이트). 도메인 모양이 틀렸거나 브라우저에 아이콘이 없으면 None."""
        if not is_valid_domain(domain):
            return None
        png = self._cached(domain)
        if png is None:
            if self._is_known_missing(domain):
                return None
            png = self._read_from_chrome(domain)
            if png is None:
                with self._guard:
                    self._missing_until[domain] = time.monotonic() + _NEGATIVE_TTL_SECONDS
                return None
            self._remember(domain, png)
        # 키는 내용의 해시라, Chrome이 아이콘을 바꾸면 브라우저 캐시도 자연히 새로 받는다.
        return hashlib.sha256(png).hexdigest()[:32], png

    def _read_from_chrome(self, domain: str) -> bytes | None:
        patterns = _page_url_patterns(domain)
        rows: list[tuple[bytes, int, int]] = []
        for user_data_dir in self._user_data_dirs:
            for folder in profile_folders(user_data_dir):
                rows.extend(self._query_profile(user_data_dir / folder / "Favicons", patterns))
        return _pick_best(rows)

    def _query_profile(
        self, source: Path, patterns: list[str]
    ) -> list[tuple[bytes, int, int]]:
        # 이 폴더는 방문 사이트 정보를 담은 복사본이라 쓰고 나면 바로 지운다.
        work_dir = Path(tempfile.mkdtemp(prefix="whatever-log-favicons-"))
        try:
            copy = work_dir / "Favicons"
            try:
                shutil.copyfile(source, copy)
            except OSError:
                return []
            try:
                connection = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
            except sqlite3.Error:
                return []
            try:
                where = " OR ".join("m.page_url LIKE ?" for _ in patterns)
                return connection.execute(
                    "SELECT b.image_data, b.width, b.last_updated "
                    "FROM icon_mapping m JOIN favicon_bitmaps b ON b.icon_id = m.icon_id "
                    f"WHERE {where}",
                    patterns,
                ).fetchall()
            except sqlite3.Error:
                return []
            finally:
                connection.close()
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _cached(self, domain: str) -> bytes | None:
        with self._guard:
            png = self._memory.get(domain)
            if png is not None:
                self._memory.move_to_end(domain)
            return png

    def _remember(self, domain: str, png: bytes) -> None:
        with self._guard:
            self._memory[domain] = png
            self._memory.move_to_end(domain)
            while len(self._memory) > _MEMORY_ENTRIES:
                self._memory.popitem(last=False)

    def _is_known_missing(self, domain: str) -> bool:
        with self._guard:
            until = self._missing_until.get(domain)
            if until is None:
                return False
            if time.monotonic() >= until:
                del self._missing_until[domain]
                return False
            return True
