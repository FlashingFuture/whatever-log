"""로그인할 때 프로그램이 자동으로 뜨도록 등록/해제한다 (Windows Registry Run 키).

recorder와 동기화 에이전트의 supervisor가 같은 방식으로 등록되므로 한 곳에 둔다 — 값 이름과 실행할 명령만 호출부가 정한다.
Windows 서비스는 쓰지 않는다: 서비스는 Session 0에 격리돼 사용자 데스크톱(활성 창 등)에 접근할 수 없다. pythonw.exe는 콘솔 창을
띄우지 않으므로(로그는 각 프로그램이 파일로 남긴다) Run 키에 pythonw.exe로 등록한다.
"""

import subprocess
import sys
import winreg
from pathlib import Path

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


#: 릴리스 번들의 파이썬 실행 파일 이름. `whatever-log.exe`는 콘솔이 없는 쪽(pythonw의 복사본)이고, 창을 소유하는 프로세스가 이 이름이라
#: 사용 현황·작업 관리자에서 `pythonw.exe`가 아니라 앱 이름으로 보인다. `whatever-log-cli.exe`는 콘솔이 있는 쪽(python의 복사본)이다.
BUNDLED_WINDOWLESS_EXE = "whatever-log.exe"
BUNDLED_CONSOLE_EXE = "whatever-log-cli.exe"


def pythonw_path() -> Path:
    """콘솔 창 없이 모듈을 실행할 파이썬 실행 파일.

    릴리스 번들에서는 같은 폴더의 `whatever-log.exe`, 개발 환경(가상환경)에서는 `pythonw.exe`다. 번들인지는 지금 실행 중인 파이썬의
    파일 이름으로 가린다 — 가상환경의 `Scripts` 폴더에도 `whatever-log.exe`(명령 실행기)가 있어서, 파일이 있는지만 보면 개발 환경에서
    그것을 잘못 고른다.
    """
    current = Path(sys.executable)
    if current.name.lower() in (BUNDLED_WINDOWLESS_EXE, BUNDLED_CONSOLE_EXE):
        return current.with_name(BUNDLED_WINDOWLESS_EXE)
    return current.with_name("pythonw.exe")


def module_command(module: str, *args: str) -> str:
    """`pythonw.exe -m <module> <args…>` 형태의 실행 명령. 각 인자를 Windows 명령줄 규칙으로 직렬화한다.

    공백이나 따옴표가 든 인자(예: 공백이 든 `--db-path` 경로)도 한 인자로 보존된다 — 그냥 공백으로 이어 붙이면 둘로 쪼개져
    자동 시작 때 인자 오류로 죽는다.
    """
    return subprocess.list2cmdline([str(pythonw_path()), "-m", module, *args])


def enable(value_name: str, command: str) -> None:
    """로그인 시 command가 실행되도록 Registry Run 키에 value_name으로 등록한다.

    OpenKey가 아니라 CreateKeyEx를 쓴다 — 한 번도 자동시작 앱을 등록한 적 없는 깨끗한 프로필에는 Run 키 자체가 없을 수 있고,
    OpenKey는 그때 FileNotFoundError로 실패한다. pythonw.exe가 실제로 있는지 미리 확인한다 — 없는 채로 등록하면 로그인 때 조용히
    실행되지 않고 알아챌 방법이 없다(콘솔도 로그 파일도 생기지 않는다).
    """
    executable = pythonw_path()
    if not executable.exists():
        raise FileNotFoundError(f"콘솔 없는 파이썬 실행 파일을 찾을 수 없습니다: {executable}")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)


def disable(value_name: str) -> None:
    """자동 시작 등록을 해제한다. 등록되어 있지 않았어도(Run 키 자체가 없어도) 조용히 넘어간다."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, value_name)
    except FileNotFoundError:
        pass


def registered_command(value_name: str) -> str | None:
    """value_name으로 등록된 명령(없으면 None). 다른 설치본의 등록인지 가려내는 데 쓴다."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return str(value)
    except FileNotFoundError:
        return None


def is_enabled(value_name: str) -> bool:
    """value_name이 지금 등록되어 있는지 확인한다. Run 키 자체가 없으면 등록 안 된 것으로 본다."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, value_name)
            return True
    except FileNotFoundError:
        return False
