"""Chrome이 포그라운드일 때, 지금 보고 있는 사이트의 도메인을 알아낸다.

브라우저 확장 없이 얻기 위해 Chrome이 스스로 남기는 방문 기록(`History` SQLite)을 쓴다:
활성 창의 제목("페이지 제목 - 프로필 - Chrome")에서 페이지 제목을 뽑아, 방문 기록에서 같은
제목의 가장 최근 방문 URL을 찾고 도메인만 남긴다. 제목·경로·쿼리는 저장하지 않고 버린다
(docs/data-handling.md).

한계(추정이라는 점): 제목이 같은 서로 다른 사이트(새 탭 등)는 가장 최근 방문으로 고르고,
방문 기록에 아직 안 남은 페이지나 제목만 바뀐 페이지는 못 찾는다(None). 시크릿 창은
방문 기록이 없어 자연히 None이다.

Chrome은 History 파일을 쓰는 중이라 원본을 열지 않고 읽기 전용 복사본을 만들어 읽는다.
복사는 원본이 바뀌었을 때만 한다.
"""

import json
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger("recorder")

BROWSER_LABELS = frozenset({"Google Chrome", "Chrome"})

# 방문 기록이 이보다 크면 복사 비용이 틱마다 부담이라 건너뛴다(사이트 없음으로 처리).
MAX_HISTORY_BYTES = 512 * 1024 * 1024

_WORK_DIR_PREFIX = "whatever-log-history-"


@dataclass(frozen=True)
class ParsedTitle:
    """Chrome 창 제목을 나눈 결과. profile은 제목에 프로필 이름이 있을 때만 채워진다."""

    page: str
    profile: str | None


def parse_chrome_title(title: str, profile_names: frozenset[str]) -> ParsedTitle | None:
    """"페이지 - Google Chrome", "페이지 - 프로필 - Chrome" 같은 제목에서 페이지 제목을 뽑는다.

    페이지 제목 자체에도 " - "가 들어갈 수 있어서, 뒤에서부터 브라우저 이름과 알려진 프로필
    이름만 떼어낸다. Chrome 창 제목이 아니면(브라우저 이름이 없으면) None.
    """
    parts = title.split(" - ")
    profile: str | None = None
    if parts[-1] in BROWSER_LABELS:
        parts.pop()
    elif len(parts) >= 2 and parts[-2] in BROWSER_LABELS and parts[-1] in profile_names:
        profile = parts.pop()
        parts.pop()
    else:
        return None
    if profile is None and len(parts) >= 2 and parts[-1] in profile_names:
        profile = parts.pop()
    page = " - ".join(parts)
    return ParsedTitle(page, profile) if page else None


def domain_of(url: str) -> str | None:
    """URL에서 도메인(호스트)만 남긴다. http(s)가 아니거나 호스트가 없으면 None.

    앞의 "www."는 같은 사이트로 묶기 위해 뗀다. 경로·쿼리·해시는 버린다.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    return host.removeprefix("www.")


def default_user_data_dir() -> Path:
    """Windows에서 Chrome 프로필들이 있는 폴더."""
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"


def read_profile_names(user_data_dir: Path) -> dict[str, str]:
    """{프로필 폴더 이름: 표시 이름}. `Local State`를 못 읽으면 빈 딕셔너리."""
    try:
        state = json.loads((user_data_dir / "Local State").read_text(encoding="utf-8"))
        cache = state["profile"]["info_cache"]
        return {folder: info["name"] for folder, info in cache.items() if "name" in info}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _remove_stale_work_dirs() -> None:
    """recorder가 비정상 종료해 close()가 못 불린 복사본이 임시 폴더에 남아 있으면 지운다.

    방문 기록의 사본이 디스크에 오래 남지 않게 하려는 것이다. recorder는 lock으로 한 번에
    하나만 뜨므로(ChromeSiteResolver는 lock을 잡은 뒤에 만들어진다) 다른 실행의 폴더를
    지울 염려가 없다.
    """
    for stale in Path(tempfile.gettempdir()).glob(f"{_WORK_DIR_PREFIX}*"):
        shutil.rmtree(stale, ignore_errors=True)


class ChromeSiteResolver:
    """창 제목으로 지금 보는 사이트의 도메인을 찾는다. 읽기 전용이고 상태는 복사본 캐시뿐이다."""

    def __init__(self, user_data_dir: Path | None = None) -> None:
        self._user_data_dir = user_data_dir or default_user_data_dir()
        _remove_stale_work_dirs()
        self._work_dir = Path(tempfile.mkdtemp(prefix=_WORK_DIR_PREFIX))
        # 프로필 폴더 -> (원본 mtime_ns, size, 복사본 경로). 같으면 다시 복사하지 않는다.
        self._copies: dict[str, tuple[int, int, Path]] = {}

    def close(self) -> None:
        """복사본을 지운다. 방문 기록의 사본이 디스크에 남지 않게 종료 때 부른다."""
        shutil.rmtree(self._work_dir, ignore_errors=True)
        self._copies.clear()

    def resolve(self, window_title: str) -> str | None:
        """Chrome 창 제목에 해당하는 도메인. 못 찾으면 None."""
        profiles = read_profile_names(self._user_data_dir)
        parsed = parse_chrome_title(window_title, frozenset(profiles.values()))
        if parsed is None:
            return None
        folders = [
            folder
            for folder, name in profiles.items()
            if parsed.profile is None or name == parsed.profile
        ]
        # 프로필을 모를 땐 여러 프로필을 다 찾아, 방문 시각이 가장 최근인 결과를 쓴다.
        best: tuple[int, str] | None = None
        for folder in folders:
            found = self._lookup(folder, parsed.page)
            if found is not None and (best is None or found[0] > best[0]):
                best = found
        return best[1] if best else None

    def _lookup(self, folder: str, page: str) -> tuple[int, str] | None:
        copy = self._history_copy(folder)
        if copy is None:
            return None
        try:
            connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        try:
            rows = connection.execute(
                "SELECT url, last_visit_time FROM urls WHERE title = ? "
                "ORDER BY last_visit_time DESC LIMIT 5",
                (page,),
            ).fetchall()
        except sqlite3.Error:
            return None
        finally:
            connection.close()
        for url, visited_at in rows:
            domain = domain_of(url)
            if domain:
                return visited_at, domain
        return None

    def _history_copy(self, folder: str) -> Path | None:
        source = self._user_data_dir / folder / "History"
        try:
            stat = source.stat()
        except OSError:
            return None
        if stat.st_size > MAX_HISTORY_BYTES:
            return None
        cached = self._copies.get(folder)
        if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
            return cached[2]
        target = self._work_dir / f"{folder.replace(' ', '_')}.db"
        try:
            shutil.copyfile(source, target)
        except OSError:
            return None
        self._copies[folder] = (stat.st_mtime_ns, stat.st_size, target)
        return target


class SiteTracker:
    """틱마다 "Chrome이 포그라운드면 사이트 도메인"을 돌려주는 얇은 껍데기.

    부가 정보라서, 어떤 예외가 나도 기록 루프를 멈추지 않고 None을 돌려준다. 어느 정도
    맞았는지 보려고 Chrome이 포그라운드였던 틱 수와 도메인을 찾은 틱 수만 센다(도메인·제목은
    로그에 남기지 않는다).
    """

    def __init__(self, resolver: ChromeSiteResolver | None = None) -> None:
        self._resolver = resolver or ChromeSiteResolver()
        self.chrome_ticks = 0
        self.matched_ticks = 0

    def close(self) -> None:
        """리졸버의 복사본을 정리한다."""
        self._resolver.close()

    def site_for(self, foreground_process: str | None, window_title: str | None) -> str | None:
        """포그라운드가 chrome.exe이고 제목을 알면 도메인, 아니면 None."""
        if foreground_process != "chrome.exe":
            return None
        self.chrome_ticks += 1
        if not window_title:
            return None
        try:
            domain = self._resolver.resolve(window_title)
        except Exception:
            logger.exception("사이트 조회에 실패했습니다(이번 틱은 사이트 없음으로 기록)")
            return None
        if domain:
            self.matched_ticks += 1
        return domain
