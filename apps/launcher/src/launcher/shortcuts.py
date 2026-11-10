"""시작 메뉴·바탕화면 바로가기를 만든다 (Windows).

바로가기가 앱 아이콘을 가진다 — 이 앱은 pythonw.exe로 뜨기 때문에 바로가기가 없으면 파이썬 아이콘으로 보인다. 바로가기는
`pythonw.exe -m launcher start`(백그라운드 구성 요소를 확인하고 창을 연다)를 실행한다.

.lnk 파일은 윈도우 기본 기능(WScript.Shell)으로 만든다 — 추가 패키지 없이 PowerShell 한 번이면 된다. 경로는 명령줄이 아니라
환경변수로 넘겨서 경로에 따옴표나 공백이 있어도 스크립트가 깨지지 않게 한다.
"""

import ctypes
import os
import subprocess
from pathlib import Path

from desktop.window_icon import ICON_PATH
from supervision.autostart import pythonw_path

from launcher.components import REPO_ROOT


def system_directory() -> Path:
    """윈도우의 시스템 폴더(`…\\Windows\\System32`)를 윈도우 API(GetSystemDirectoryW)로 구한다.

    환경변수 `SystemRoot`나 고정된 `C:\\Windows`에 기대지 않는다 — 환경변수는 지워지거나 바뀔 수 있고, 윈도우가 D:에 설치된 PC도 있다.
    """
    buffer = ctypes.create_unicode_buffer(260)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise OSError("윈도우 시스템 폴더를 찾지 못했어요.")
    return Path(buffer.value)


def powershell_path() -> str:
    """Windows PowerShell의 전체 경로. 이름만 주면 Windows가 현재 폴더·PATH에서도 찾으므로, 거기 놓인 다른 powershell.exe가
    대신 실행될 수 있다 — 시스템 폴더의 것만 쓴다."""
    return str(system_directory() / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def powershell_env(**extra: str) -> dict[str, str]:
    """PowerShell(자식 프로세스)에 넘길 환경. `SystemRoot`가 없으면 시스템 폴더에서 구해 채운다 — 없으면 PowerShell·COM이 시작하지 못한다."""
    env = {**os.environ, **extra}
    # 윈도우의 환경변수 이름은 대소문자를 가리지 않는다 — os.environ을 복사한 일반 dict의 키는 대문자(SYSTEMROOT)라서, 그대로 "SystemRoot"를
    # 찾으면 이미 있어도 없다고 보고 같은 변수를 대소문자만 다르게 한 번 더 넣게 된다
    if not any(name.upper() == "SYSTEMROOT" and value for name, value in env.items()):
        env["SystemRoot"] = str(system_directory().parent)
    return env


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
    """현재 사용자의 바탕화면 폴더. OneDrive로 옮겨진 경우도 윈도우에 직접 물어서 맞춘다.

    PowerShell의 출력을 문자열로 받으면 콘솔 코드 페이지에 따라 한글 경로가 깨질 수 있어서, 윈도우 API(SHGetKnownFolderPath)를 유니코드 그대로 부른다.
    """
    folder_id = _Guid(0xB4BFCC3A, 0xDB2C, 0x424C, (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))  # FOLDERID_Desktop
    path = ctypes.c_wchar_p()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(path))
    if result != 0 or not path.value:
        raise OSError(f"바탕화면 폴더를 찾지 못했어요(HRESULT {result:#x}).")
    try:
        return Path(path.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)


class _Guid(ctypes.Structure):
    """윈도우 GUID 구조체(폴더 ID를 API에 넘기는 데 쓴다)."""

    _fields_ = (
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    )


def create(directory: Path) -> Path:
    """directory에 whatever.log 바로가기를 만든다(이미 있으면 덮어쓴다). 만든 파일 경로를 돌려준다."""
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / SHORTCUT_NAME
    env = powershell_env(
        WL_LINK=str(link),
        WL_TARGET=str(pythonw_path()),
        WL_ARGS="-m launcher start",
        WL_CWD=str(REPO_ROOT),
        WL_ICON=f"{ICON_PATH},0",
    )
    subprocess.run([powershell_path(), "-NoProfile", "-Command", _SCRIPT], env=env, check=True, capture_output=True)
    return link


_READ_SCRIPT = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:WL_LINK);"
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
    "$s.WorkingDirectory"
)


def working_directory(link: Path) -> Path | None:
    """바로가기가 가리키는 작업 폴더(어느 설치본의 바로가기인지 알아보는 데 쓴다). 읽지 못하면 None."""
    result = subprocess.run(
        [powershell_path(), "-NoProfile", "-Command", _READ_SCRIPT],
        env=powershell_env(WL_LINK=str(link)),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    text = result.stdout.strip()
    return Path(text) if result.returncode == 0 and text else None


def is_ours(link: Path) -> bool:
    """이 설치본(REPO_ROOT)이 만든 바로가기인지. 다른 clone이 만든 같은 이름의 바로가기는 우리 것이 아니다."""
    folder = working_directory(link)
    return folder is not None and folder.resolve() == REPO_ROOT.resolve()


class ForeignShortcut(Exception):
    """같은 이름의 바로가기가 있지만 다른 설치본의 것이라 지우지 않았다."""


def remove(directory: Path) -> bool:
    """directory의 바로가기를 지운다. 없었으면 False, 다른 설치본의 것이면 ForeignShortcut, 지우지 못하면 OSError."""
    link = directory / SHORTCUT_NAME
    if not link.exists():
        return False
    if not is_ours(link):
        raise ForeignShortcut(str(link))
    link.unlink()
    return True
