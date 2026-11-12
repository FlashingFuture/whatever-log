"""`whatever-log` 명령: 설치와 전체 실행을 한 곳에서 한다.

    whatever-log install      자동 시작·바로가기 등록, 화면 빌드, 기록기·동기화 에이전트 시작
    whatever-log start        꺼져 있는 구성 요소를 띄우고 창을 연다(시작 메뉴 바로가기가 하는 일)
    whatever-log stop         기록기·동기화 에이전트를 끈다
    whatever-log status       지금 무엇이 떠 있고 무엇이 등록됐는지 본다
    whatever-log uninstall    끄고 자동 시작·바로가기를 지운다(데이터는 그대로)
    whatever-log import-data --from <개발 폴더>   개발 폴더의 기록·목표를 이 설치본으로 복사한다(원본은 그대로)

`install --dry-run`은 아무것도 바꾸지 않고 할 일만 보여 준다.
"""

import argparse
import sys
from pathlib import Path

from common import paths

from launcher import commands, data_import


def _say(message: str) -> None:
    """콘솔이 있을 때만 출력한다(시작 메뉴 바로가기는 pythonw로 돌아 sys.stdout이 없다)."""
    if sys.stdout is not None:
        print(message)


def build_parser() -> argparse.ArgumentParser:
    """명령줄 인자 정의."""
    parser = argparse.ArgumentParser(prog="whatever-log", description="whatever.log 설치와 전체 실행")
    parser.add_argument("--version", action="version", version=f"whatever.log {paths.version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="자동 시작·바로가기 등록, 화면 빌드, 구성 요소 시작")
    install.add_argument("--dry-run", action="store_true", help="아무것도 바꾸지 않고 할 일만 보여 준다")
    install.add_argument("--desktop-shortcut", action="store_true", help="바탕화면에도 바로가기를 만든다")
    install.add_argument("--skip-ui-build", action="store_true", help="화면 빌드를 건너뛴다")
    install.add_argument("--no-start", action="store_true", help="등록만 하고 지금 시작하지는 않는다")

    uninstall = sub.add_parser("uninstall", help="끄고 자동 시작·바로가기를 지운다(데이터는 그대로)")
    uninstall.add_argument("--dry-run", action="store_true", help="아무것도 바꾸지 않고 할 일만 보여 준다")

    start = sub.add_parser("start", help="꺼져 있는 구성 요소를 띄우고 창을 연다")
    start.add_argument("--no-window", action="store_true", help="백그라운드 구성 요소만 띄우고 창은 열지 않는다")

    imp = sub.add_parser("import-data", help="개발용 저장소에 쌓인 기록·목표를 이 설치본의 데이터 폴더로 복사한다(원본은 그대로)")
    imp.add_argument("--from", dest="source", required=True, type=Path, help="개발용 저장소 폴더(apps/recorder 등이 들어 있는 폴더)")
    imp.add_argument("--dry-run", action="store_true", help="아무것도 바꾸지 않고 할 일만 보여 준다")
    imp.add_argument("--replace", action="store_true", help="이미 있는 데이터는 <이름>.before-import로 옮기고 가져온다")

    sub.add_parser("stop", help="기록기·동기화 에이전트를 끈다")
    sub.add_parser("status", help="실행·등록 상태를 본다")
    return parser


def main(argv: list[str] | None = None) -> None:
    """인자에 맞는 동작을 실행한다. 일부라도 실패하면(설치·제거·시작·종료 모두) 종료 코드 1."""
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")  # Python 3.14는 아직 Windows에서 UTF-8이 기본이 아니다
    args = build_parser().parse_args(argv)

    if args.command == "install":
        ok = commands.install(
            _say,
            dry_run=args.dry_run,
            desktop_shortcut=args.desktop_shortcut,
            build_ui=not args.skip_ui_build,
            start_now=not args.no_start,
        )
        sys.exit(0 if ok else 1)
    elif args.command == "uninstall":
        sys.exit(0 if commands.uninstall(_say, dry_run=args.dry_run) else 1)
    elif args.command == "start":
        sys.exit(0 if commands.start(_say, open_window=not args.no_window) else 1)
    elif args.command == "import-data":
        sys.exit(0 if data_import.run(args.source, _say, dry_run=args.dry_run, replace=args.replace) else 1)
    elif args.command == "stop":
        sys.exit(0 if commands.stop(_say) else 1)
    else:
        commands.status(_say)


if __name__ == "__main__":
    main()
