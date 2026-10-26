"""로그인 시 supervisor가 자동으로 뜨도록 등록/해제한다 (Windows Registry Run 키).

Windows 서비스는 안 쓴다 — Session 0 격리 때문에 서비스는 recorder가 필요로
하는 사용자 데스크톱(GetForegroundWindow 등)에 접근할 수 없다. 대신 Registry
Run 키에 pythonw.exe로 supervisor를 등록한다 — pythonw.exe는 콘솔 창을 띄우지
않고, recorder.__main__의 로깅은 콘솔 없는 환경(stdout=None)을 이미 감안해서
만들어져 있다.

사용법:
    python -m recorder.autostart --enable
    python -m recorder.autostart --disable
    python -m recorder.autostart --status
"""

import argparse
import sys
import winreg
from pathlib import Path

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "WhateverLogRecorder"

# Python 3.14는 아직 Windows에서 UTF-8을 기본으로 쓰지 않는다(3.15부터 기본값).
if sys.platform == "win32" and sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")


def _pythonw_path() -> Path:
    return Path(sys.executable).with_name("pythonw.exe")


def _command() -> str:
    return f'"{_pythonw_path()}" -m recorder.supervisor'


def enable() -> None:
    """로그인 시 supervisor가 자동으로 뜨도록 Registry Run 키에 등록한다.

    OpenKey가 아니라 CreateKeyEx를 쓴다 — 한 번도 자동시작 앱을 등록한 적
    없는 깨끗한 프로필에는 Run 키 자체가 없을 수 있고, 그 상태에서
    OpenKey는 FileNotFoundError로 실패한다. CreateKeyEx는 이미 있으면 그걸
    열고, 없으면 만들어서 연다.

    pythonw.exe가 실제로 있는지 미리 확인한다 — 없는 채로 등록해버리면
    로그인 시점에 조용히 실행이 안 되고, 그걸 알아챌 방법이 없다(콘솔도
    없고 recorder.log도 아예 안 생김).
    """
    pythonw_path = _pythonw_path()
    if not pythonw_path.exists():
        raise FileNotFoundError(f"pythonw.exe를 찾을 수 없습니다: {pythonw_path}")

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _command())


def disable() -> None:
    """자동 시작 등록을 해제한다. 등록되어 있지 않았어도(Run 키 자체가 없어도) 조용히 넘어간다."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        pass


def is_enabled() -> bool:
    """자동 시작이 지금 등록되어 있는지 확인한다. Run 키 자체가 없으면 등록 안 된 것으로 본다."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def main() -> None:
    """CLI 인자(`--enable`/`--disable`/`--status`)를 파싱해서 해당 동작을 실행한다."""
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")

    parser = argparse.ArgumentParser(description="로그인 시 recorder 자동 시작 등록/해제")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true", help="자동 시작 등록")
    group.add_argument("--disable", action="store_true", help="자동 시작 해제")
    group.add_argument("--status", action="store_true", help="등록 여부 확인")
    args = parser.parse_args()

    if args.enable:
        enable()
        print("등록했습니다. 다음 로그인부터 자동으로 시작됩니다.")
    elif args.disable:
        disable()
        print("해제했습니다.")
    else:
        print("등록됨" if is_enabled() else "등록 안 됨")


if __name__ == "__main__":
    main()
