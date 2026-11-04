"""Chromium 계열 브라우저(Chrome, Edge, Brave, Vivaldi)의 이름·프로세스·데이터 위치.

이 브라우저들은 같은 엔진이라 방문 기록(`History`)·아이콘(`Favicons`)·프로필 목록(`Local State`)의
형식이 같다. 달라지는 건 프로세스 이름, 창 제목 끝에 붙는 브라우저 이름, 사용자 데이터 폴더뿐이라
이 표 하나로 묶는다. 브라우저를 더하려면 여기에 한 줄 추가하면 된다(화면 쪽
`apps/ui/src/browsers.ts`의 프로세스 목록도 같이 맞춘다).

Firefox(places.sqlite)와 Opera(프로필 폴더 구조가 다름)는 형식이 달라 포함하지 않는다.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Browser:
    """브라우저 하나. 창 제목은 "페이지 제목 - 프로필 - <title_labels 중 하나>" 꼴이다."""

    key: str
    process_name: str
    title_labels: frozenset[str]
    user_data_subpath: tuple[str, ...]

    def user_data_dir(self) -> Path:
        """Windows에서 이 브라우저의 프로필들이 있는 폴더."""
        return Path(os.environ.get("LOCALAPPDATA", "")).joinpath(*self.user_data_subpath)


BROWSERS: tuple[Browser, ...] = (
    Browser(
        "chrome",
        "chrome.exe",
        frozenset({"Google Chrome", "Chrome"}),
        ("Google", "Chrome", "User Data"),
    ),
    Browser(
        "edge",
        "msedge.exe",
        frozenset({"Microsoft Edge", "Edge"}),
        ("Microsoft", "Edge", "User Data"),
    ),
    Browser(
        "brave",
        "brave.exe",
        frozenset({"Brave"}),
        ("BraveSoftware", "Brave-Browser", "User Data"),
    ),
    Browser(
        "vivaldi",
        "vivaldi.exe",
        frozenset({"Vivaldi"}),
        ("Vivaldi", "User Data"),
    ),
)

BROWSER_BY_PROCESS: dict[str, Browser] = {browser.process_name: browser for browser in BROWSERS}
