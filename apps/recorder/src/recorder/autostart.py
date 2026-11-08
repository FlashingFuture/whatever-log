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

from supervision import autostart as run_key

VALUE_NAME = "WhateverLogRecorder"

# Python 3.14는 아직 Windows에서 UTF-8을 기본으로 쓰지 않는다(3.15부터 기본값).
if sys.platform == "win32" and sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")


def _command() -> str:
    return run_key.module_command("recorder.supervisor")


def enable() -> None:
    """로그인 시 recorder supervisor가 자동으로 뜨도록 Registry Run 키에 등록한다(실제 등록은 supervision.autostart)."""
    run_key.enable(VALUE_NAME, _command())


def disable() -> None:
    """자동 시작 등록을 해제한다. 등록되어 있지 않았어도 조용히 넘어간다."""
    run_key.disable(VALUE_NAME)


def is_enabled() -> bool:
    """자동 시작이 지금 등록되어 있는지 확인한다."""
    return run_key.is_enabled(VALUE_NAME)


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
