"""foreground / 전체 윈도우 프로세스 / 입력 활동을 interval마다 샘플링해서
SQLite에 저장하는 워커.

사용법: python -m recorder --interval 5
"""

import argparse
import sys
import time
from pathlib import Path

from recorder.sampling import sample_tick
from recorder.storage import open_db, save_tick

DEFAULT_INTERVAL_SECONDS = 15.0

# 1초보다 짧으면 프로세스 목록 조회(EnumWindows 등)가 과도하게 반복 호출되어
# 시스템에 부담을 줄 수 있다 — CLI 인자로 그런 값을 넣는 걸 막는다.
MIN_INTERVAL_SECONDS = 1.0

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "recorder.db"

# Python 3.14는 아직 Windows에서 UTF-8을 기본으로 쓰지 않는다(3.15부터 기본값).
# 터미널 코드페이지에 따라 한글이 깨지는 걸 막기 위해 명시적으로 맞춘다.
# argparse 에러 메시지는 stderr로 나가므로 둘 다 맞춰야 한다.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _interval_type(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}'는 숫자가 아닙니다.") from exc

    if parsed < MIN_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(
            f"--interval은 최소 {MIN_INTERVAL_SECONDS}초 이상이어야 합니다 "
            "(너무 짧으면 과도한 프로세스 조회로 시스템에 부담을 줄 수 있습니다)."
        )
    return parsed


def run(interval: float, db_path: Path) -> None:
    """DB를 열어두고 interval마다 한 틱씩 기록하는 메인 루프. Ctrl+C로 종료한다."""
    conn = open_db(db_path)
    tick_count = 0
    print(f"{interval}초 간격으로 기록합니다. DB: {db_path} (Ctrl+C로 종료)")

    try:
        while True:
            sample = sample_tick()
            save_tick(conn, sample)
            tick_count += 1
            print(
                f"[tick {tick_count}] FG={sample.foreground_process} "
                f"WIN={len(sample.windowed_processes)}개 "
                f"idle={sample.seconds_since_last_input:.1f}s"
            )
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n종료합니다. 총 {tick_count}틱 기록됨 ({db_path})")
    finally:
        conn.close()


def main() -> None:
    """CLI 인자(`--interval`, `--db-path`)를 파싱해서 run()에 넘기는 진입점."""
    parser = argparse.ArgumentParser(description="foreground / 전체 윈도우 프로세스 기록 워커")
    parser.add_argument(
        "--interval",
        type=_interval_type,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"샘플링 간격(초), 최소 {MIN_INTERVAL_SECONDS}초, 기본 {DEFAULT_INTERVAL_SECONDS}초",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 파일 경로 (기본: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()
    run(args.interval, args.db_path)


if __name__ == "__main__":
    main()
