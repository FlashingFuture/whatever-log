"""시작 메뉴·바탕화면 바로가기를 만든다 (Windows).

바로가기가 앱 아이콘을 가진다 — 이 앱은 pythonw.exe로 뜨기 때문에 바로가기가 없으면 파이썬 아이콘으로 보인다. 바로가기는
`pythonw.exe -m launcher start`(백그라운드 구성 요소를 확인하고 창을 연다)를 실행한다.

.lnk 파일은 윈도우 기본 기능(WScript.Shell)으로 만든다 — 추가 패키지 없이 PowerShell 한 번이면 된다. 경로는 명령줄이 아니라
환경변수로 넘겨서 경로에 따옴표나 공백이 있어도 스크립트가 깨지지 않게 한다.
"""

import os
import subprocess
from pathlib import Path

from desktop.window_icon import ICON_PATH
from supervision.autostart import pythonw_path

from launcher.components import REPO_ROOT

SHORTCUT_NAME = "whatever.log.lnk"

_SCRIPT = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:WL_LINK);"
    "$s.TargetPath = $env:WL_TARGET;"
    "$s.Arguments = $env:WL_ARGS;"
    "$s.WorkingDirectory = $env:WL_CWD;"
    "$s.IconLocation = $env:WL_ICON;"
    "$s.Description = 'whatever.log';"
    "$s.Save()"
)


def start_menu_dir() -> Path:
    """현재 사용자의 시작 메뉴 '프로그램' 폴더."""
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_dir() -> Path:
    """현재 사용자의 바탕화면 폴더(OneDrive로 옮겨진 경우도 윈도우에 물어서 맞춘다)."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def create(directory: Path) -> Path:
    """directory에 whatever.log 바로가기를 만든다(이미 있으면 덮어쓴다). 만든 파일 경로를 돌려준다."""
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / SHORTCUT_NAME
    env = {
        **os.environ,
        "WL_LINK": str(link),
        "WL_TARGET": str(pythonw_path()),
        "WL_ARGS": "-m launcher start",
        "WL_CWD": str(REPO_ROOT),
        "WL_ICON": f"{ICON_PATH},0",
    }
    subprocess.run(["powershell", "-NoProfile", "-Command", _SCRIPT], env=env, check=True, capture_output=True)
    return link


def remove(directory: Path) -> bool:
    """directory의 바로가기를 지운다. 없었으면 False."""
    link = directory / SHORTCUT_NAME
    if not link.exists():
        return False
    link.unlink()
    return True
