"""로그인할 때 프로그램이 자동으로 뜨도록 등록/해제한다 (Windows Registry Run 키).

recorder와 동기화 에이전트의 supervisor가 같은 방식으로 등록되므로 한 곳에 둔다 — 값 이름과 실행할 명령만 호출부가 정한다.
Windows 서비스는 쓰지 않는다: 서비스는 Session 0에 격리돼 사용자 데스크톱(활성 창 등)에 접근할 수 없다. pythonw.exe는 콘솔 창을
띄우지 않으므로(로그는 각 프로그램이 파일로 남긴다) Run 키에 pythonw.exe로 등록한다.
"""

import sys
import winreg
from pathlib import Path

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def pythonw_path() -> Path:
    """지금 파이썬(가상환경)의 pythonw.exe. 콘솔 창 없이 모듈을 실행하는 데 쓴다."""
    return Path(sys.executable).with_name("pythonw.exe")


def module_command(module: str, *args: str) -> str:
    """`pythonw.exe -m <module> <args…>` 형태의 실행 명령(경로에 공백이 있어도 되게 따옴표로 감싼다)."""
    parts = [f'"{pythonw_path()}"', "-m", module, *args]
    return " ".join(parts)


def enable(value_name: str, command: str) -> None:
    """로그인 시 command가 실행되도록 Registry Run 키에 value_name으로 등록한다.

    OpenKey가 아니라 CreateKeyEx를 쓴다 — 한 번도 자동시작 앱을 등록한 적 없는 깨끗한 프로필에는 Run 키 자체가 없을 수 있고,
    OpenKey는 그때 FileNotFoundError로 실패한다. pythonw.exe가 실제로 있는지 미리 확인한다 — 없는 채로 등록하면 로그인 때 조용히
    실행되지 않고 알아챌 방법이 없다(콘솔도 로그 파일도 생기지 않는다).
    """
    executable = pythonw_path()
    if not executable.exists():
        raise FileNotFoundError(f"pythonw.exe를 찾을 수 없습니다: {executable}")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)


def disable(value_name: str) -> None:
    """자동 시작 등록을 해제한다. 등록되어 있지 않았어도(Run 키 자체가 없어도) 조용히 넘어간다."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, value_name)
    except FileNotFoundError:
        pass


def is_enabled(value_name: str) -> bool:
    """value_name이 지금 등록되어 있는지 확인한다. Run 키 자체가 없으면 등록 안 된 것으로 본다."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, value_name)
            return True
    except FileNotFoundError:
        return False
