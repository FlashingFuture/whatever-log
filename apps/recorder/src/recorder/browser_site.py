"""브라우저가 포그라운드일 때, 지금 보고 있는 사이트의 도메인을 알아낸다.

Chromium 계열(Chrome, Edge, Brave, Vivaldi)을 지원한다. 브라우저 확장 없이 얻기 위해 브라우저가
스스로 남기는 방문 기록(`History` SQLite)을 쓴다: 활성 창의 제목("페이지 제목 - 프로필 - 브라우저
이름")에서 페이지 제목을 뽑아, 방문 기록에서 같은 제목의 가장 최근 방문 URL을 찾고 도메인만
남긴다. 제목·경로·쿼리는 저장하지 않고 버린다(docs/data-handling.md).

한계(추정이라는 점): 제목이 같은 서로 다른 사이트(새 탭 등)는 가장 최근 방문으로 고르고,
방문 기록에 아직 안 남은 페이지나 제목만 바뀐 페이지는 못 찾는다(None). 시크릿 창은
방문 기록이 없어 자연히 None이다.

브라우저는 History 파일을 쓰는 중이라 원본을 열지 않고 읽기 전용 복사본을 만들어 읽는다.
복사는 원본이 바뀌었을 때만 한다.
"""

import logging
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chromium.browsers import BROWSER_BY_PROCESS, Browser
from chromium.profiles import read_profile_names
from chromium.urls import domain_of

logger = logging.getLogger("recorder")

# 방문 기록이 이보다 크면 복사 비용이 틱마다 부담이라 건너뛴다(사이트 없음으로 처리).
MAX_HISTORY_BYTES = 512 * 1024 * 1024

_WORK_DIR_PREFIX = "whatever-log-history-"

# Edge는 창 제목의 "Microsoft Edge" 안에 보이지 않는 글자(zero-width space)를 넣는다 — 그대로
# 비교하면 브라우저 이름이 안 맞는다.
_INVISIBLE_CHARS = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


# Edge는 창에 탭이 여러 개일 때 활성 탭 제목 뒤에 "외 페이지 3개"(영어는 "and 3 more pages")를
# 붙인다 — 방문 기록의 제목에는 없는 글자라 떼어내야 찾을 수 있다.
_MORE_PAGES_SUFFIX = re.compile(r"(?: 외 페이지 \d+개| and \d+ more pages?)$")


@dataclass(frozen=True)
class ParsedTitle:
    """브라우저 창 제목을 나눈 결과. profile은 제목에 프로필 이름이 있을 때만 채워진다."""

    page: str
    profile: str | None


def parse_browser_title(
    title: str, browser_labels: frozenset[str], profile_names: frozenset[str]
) -> ParsedTitle | None:
    """"페이지 - 브라우저", "페이지 - 프로필 - 브라우저" 같은 제목에서 페이지 제목을 뽑는다.

    페이지 제목 자체에도 " - "가 들어갈 수 있어서, 뒤에서부터 브라우저 이름과 알려진 프로필
    이름만 떼어낸다. 그 브라우저의 창 제목이 아니면(브라우저 이름이 없으면) None.
    """
    parts = title.translate(_INVISIBLE_CHARS).split(" - ")
    profile: str | None = None
    if parts[-1] in browser_labels:
        parts.pop()
    elif len(parts) >= 2 and parts[-2] in browser_labels and parts[-1] in profile_names:
        profile = parts.pop()
        parts.pop()
    else:
        return None
    if profile is None and len(parts) >= 2 and parts[-1] in profile_names:
        profile = parts.pop()
    page = _MORE_PAGES_SUFFIX.sub("", " - ".join(parts))
    return ParsedTitle(page, profile) if page else None


def title_candidates(
    title: str, browser_labels: frozenset[str], profile_names: frozenset[str]
) -> list[ParsedTitle]:
    """창 제목에서 페이지 제목일 수 있는 후보들을 가능성이 높은 순서로 돌려준다.

    첫 후보는 parse_browser_title의 결과다. 제목에 프로필 이름이 있는데 Local State에 적힌
    이름과 다르게 표시되는 경우(Edge가 "개인"처럼 프로필 종류를 보여 주는 등)에는 알려진
    프로필로 걸러지지 않아 그 이름이 페이지 제목에 섞인다. 그래서 마지막 " - " 조각을 모르는
    프로필 이름으로 보고 뗀 후보를 하나 더 낸다 — 앞의 후보가 방문 기록에 없을 때만 쓰이므로
    일반 페이지 제목의 " - "를 잘못 떼어 낼 일은 드물다.
    """
    first = parse_browser_title(title, browser_labels, profile_names)
    if first is None:
        return []
    candidates = [first]
    if first.profile is None and " - " in first.page:
        stripped = _MORE_PAGES_SUFFIX.sub("", first.page.rsplit(" - ", 1)[0])
        if stripped:
            candidates.append(ParsedTitle(stripped, None))
    return candidates


def remove_stale_work_dirs() -> None:
    """recorder가 비정상 종료해 close()가 못 불린 복사본이 임시 폴더에 남아 있으면 지운다.

    방문 기록의 사본이 디스크에 오래 남지 않게 하려는 것이다. recorder는 lock으로 한 번에
    하나만 뜨므로(SiteTracker는 lock을 잡은 뒤에 만들어진다) 다른 실행의 폴더를 지울 염려가
    없다. 브라우저마다 만드는 리졸버가 서로의 폴더를 지우지 않게, 추적기를 만들 때 한 번만 부른다.
    """
    for stale in Path(tempfile.gettempdir()).glob(f"{_WORK_DIR_PREFIX}*"):
        shutil.rmtree(stale, ignore_errors=True)


class BrowserSiteResolver:
    """한 브라우저의 창 제목으로 지금 보는 사이트의 도메인을 찾는다. 상태는 복사본 캐시뿐이다."""

    def __init__(self, browser: Browser, user_data_dir: Path | None = None) -> None:
        self._browser = browser
        self._user_data_dir = user_data_dir or browser.user_data_dir()
        self._work_dir = Path(tempfile.mkdtemp(prefix=_WORK_DIR_PREFIX))
        # 프로필 폴더 -> (원본 mtime_ns, size, 복사본 경로). 같으면 다시 복사하지 않는다.
        self._copies: dict[str, tuple[int, int, Path]] = {}

    def close(self) -> None:
        """복사본을 지운다. 방문 기록의 사본이 디스크에 남지 않게 종료 때 부른다."""
        shutil.rmtree(self._work_dir, ignore_errors=True)
        self._copies.clear()

    def resolve(self, window_title: str) -> str | None:
        """브라우저 창 제목에 해당하는 도메인. 못 찾으면 None."""
        profiles = read_profile_names(self._user_data_dir)
        for parsed in title_candidates(
            window_title, self._browser.title_labels, frozenset(profiles.values())
        ):
            domain = self._resolve_page(parsed, profiles)
            if domain is not None:
                return domain
        return None

    def _resolve_page(self, parsed: ParsedTitle, profiles: dict[str, str]) -> str | None:
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
    """틱마다 "브라우저가 포그라운드면 사이트 도메인"을 돌려주는 얇은 껍데기.

    브라우저마다 리졸버를 처음 필요할 때 만든다(설치하지 않은 브라우저는 만들 일이 없다).
    부가 정보라서, 어떤 예외가 나도 기록 루프를 멈추지 않고 None을 돌려준다. 어느 정도
    맞았는지 보려고 브라우저가 포그라운드였던 틱 수와 도메인을 찾은 틱 수만 센다(도메인·제목은
    로그에 남기지 않는다).
    """

    def __init__(self, resolvers: dict[str, BrowserSiteResolver] | None = None) -> None:
        remove_stale_work_dirs()
        # 프로세스 이름 -> 리졸버. 테스트가 가짜 리졸버를 넣을 수 있게 열어 둔다.
        self._resolvers: dict[str, BrowserSiteResolver] = resolvers if resolvers is not None else {}
        self.browser_ticks = 0
        self.matched_ticks = 0

    def close(self) -> None:
        """리졸버들의 복사본을 정리한다."""
        for resolver in self._resolvers.values():
            resolver.close()

    def is_browser(self, process_name: str | None) -> bool:
        """사이트를 알아낼 수 있는(지원하는) 브라우저 프로세스인지."""
        return process_name in BROWSER_BY_PROCESS

    def site_for(self, foreground_process: str | None, window_title: str | None) -> str | None:
        """포그라운드가 지원하는 브라우저이고 제목을 알면 도메인, 아니면 None."""
        browser = BROWSER_BY_PROCESS.get(foreground_process or "")
        if browser is None:
            return None
        self.browser_ticks += 1
        if not window_title:
            return None
        try:
            resolver = self._resolvers.get(browser.process_name)
            if resolver is None:
                resolver = self._resolvers[browser.process_name] = BrowserSiteResolver(browser)
            domain = resolver.resolve(window_title)
        except Exception:
            logger.exception("사이트 조회에 실패했습니다(이번 틱은 사이트 없음으로 기록)")
            return None
        if domain:
            self.matched_ticks += 1
        return domain
