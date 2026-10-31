"""foreground / 전체 윈도우 프로세스 / 입력 활동을 interval마다 샘플링해서
SQLite에 저장하는 워커.

사용법: python -m recorder --interval 5

백그라운드(콘솔 없이, pythonw.exe 등)로 실행하면 sys.stdout/stderr가 None이
된다 — 그래서 상태는 print()가 아니라 파일 로그로 남긴다.
"""

import argparse
import logging
import math
import sqlite3
import sys
import time
from pathlib import Path

from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from supervision.log_setup import configure_logging
from recorder.process_paths import resolve_exe_paths
from recorder.sampling import TickSample, sample_tick
from recorder.storage import open_db, save_process_paths, save_tick
from supervision.lock import AlreadyRunningError, acquire_lock

DEFAULT_INTERVAL_SECONDS = 15.0

# 1초보다 짧으면 프로세스 목록 조회(EnumWindows 등)가 과도하게 반복 호출되어
# 시스템에 부담을 줄 수 있다 — CLI 인자로 그런 값을 넣는 걸 막는다.
MIN_INTERVAL_SECONDS = 1.0

_APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = _APP_DIR / "recorder.db"
DEFAULT_LOG_PATH = _APP_DIR / "recorder.log"

logger = logging.getLogger("recorder")

# Python 3.14는 아직 Windows에서 UTF-8을 기본으로 쓰지 않는다(3.15부터 기본값).
# 터미널 코드페이지에 따라 한글이 깨지는 걸 막기 위해 명시적으로 맞춘다. 콘솔 없이
# (pythonw.exe 등으로) 실행되면 sys.stdout/stderr가 None이라 이 자체가 없을 수 있다.
if sys.platform == "win32":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding="utf-8")


def _interval_type(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}'는 숫자가 아닙니다.") from exc

    # nan은 "< MIN_INTERVAL_SECONDS" 비교가 항상 거짓이라 아래 검증을 통과해버리고,
    # inf도 숫자값 비교상 통과한다. 둘 다 이후 time.sleep()에서 처리되지 않은
    # 예외(ValueError/OverflowError)로 워커가 죽으니 여기서 먼저 막는다.
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError(f"'{value}'는 유한한 숫자여야 합니다.")

    if parsed < MIN_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(
            f"--interval은 최소 {MIN_INTERVAL_SECONDS}초 이상이어야 합니다 "
            "(너무 짧으면 과도한 프로세스 조회로 시스템에 부담을 줄 수 있습니다)."
        )
    return parsed


def _lock_path_for_db(db_path: Path) -> Path:
    """lock 경로를 독립 옵션으로 두지 않고 DB 경로에서 파생시킨다.

    --db-path와 --lock-path를 따로 받으면, 같은 DB를 가리키면서 lock 경로만
    다르게 줄 수 있다 — 그러면 두 recorder가 각자 lock을 획득한 채 같은 SQLite
    파일에 동시에 쓰게 되어 lock을 두는 목적 자체가 무너진다. DB 경로 1개만
    받고 lock 경로는 항상 거기서 결정되게 해서 이 경우를 원천적으로 막는다.

    with_suffix로 확장자만 바꾸면 recorder.db와 recorder.sqlite처럼 stem은
    같고 확장자만 다른 DB들이 같은 lock 경로(recorder.lock)로 겹친다 — 이러면
    서로 다른 DB를 쓰는 두 recorder가 엉뚱하게 같은 lock을 두고 충돌한다.
    파일명 전체 뒤에 .lock을 덧붙여 DB 파일별로 lock 경로가 고유하게 한다.
    """
    resolved_db_path = db_path.resolve()
    return resolved_db_path.with_name(f"{resolved_db_path.name}.lock")


def run(interval: float, db_path: Path) -> None:
    """lock을 잡고 DB를 열어 interval마다 한 틱씩 기록하는 메인 루프.

    Ctrl+C(KeyboardInterrupt)로는 정상 종료(exit 0)하고, AlreadyRunningError는
    호출부(main)가 처리하도록 그대로 던진다. 그 외 예외는 로그에 남긴 뒤 다시
    던진다 — supervisor가 비정상 종료를 보고 재시작할 수 있도록.
    """
    lock = acquire_lock(_lock_path_for_db(db_path))
    try:
        try:
            conn = open_db(db_path)
        except Exception:
            # open_db()는 아래 틱 루프의 except Exception보다 바깥에 있어서, 안
            # 감싸면 실패해도 로그에 안 남고 그냥 전파된다 — pythonw.exe 환경에서는
            # stderr도 None이라 원인이 어디에도 안 남고, supervisor는 원인 없이
            # 재시작만 반복하게 된다.
            logger.exception("DB를 열지 못했습니다: %s", db_path)
            raise

        tick_count = 0
        # 이번 실행에서 경로 조회를 이미 시도한 프로세스 이름. 못 구한 이름도 넣어서
        # 매 틱 다시 훑지 않는다.
        path_checked: set[str] = set()
        logger.info("%s초 간격으로 기록합니다. DB: %s", interval, db_path)

        try:
            while True:
                sample = sample_tick()
                save_tick(conn, sample)
                _record_new_process_paths(conn, sample, path_checked)
                tick_count += 1
                logger.info(
                    "[tick %d] FG=%s WIN=%d개 idle=%.1fs",
                    tick_count,
                    sample.foreground_process,
                    len(sample.windowed_processes),
                    sample.seconds_since_last_input,
                )
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("종료합니다. 총 %d틱 기록됨 (%s)", tick_count, db_path)
        except Exception:
            logger.exception(
                "예기치 않은 오류로 종료합니다. 총 %d틱 기록됨 (%s)", tick_count, db_path
            )
            raise
        finally:
            conn.close()
    finally:
        lock.release()


def _record_new_process_paths(
    conn: sqlite3.Connection, sample: TickSample, checked: set[str]
) -> None:
    """이번 실행에서 처음 본 프로세스의 exe 경로를 기록한다(아이콘 표시용).

    부가 정보라서, 여기서 실패해도 틱 기록 자체를 멈추지는 않는다.
    """
    names = set(sample.windowed_processes)
    if sample.foreground_process is not None:
        names.add(sample.foreground_process)
    new_names = names - checked
    if not new_names:
        return
    checked |= new_names
    try:
        save_process_paths(conn, resolve_exe_paths(new_names))
    except Exception:
        logger.warning("프로세스 경로를 기록하지 못했습니다.", exc_info=True)


def main() -> None:
    """CLI 인자를 파싱해서 로깅을 설정하고 run()에 넘기는 진입점."""
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
    parser.add_argument(
        "--log-path",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"로그 파일 경로 (기본: {DEFAULT_LOG_PATH})",
    )
    args = parser.parse_args()
    configure_logging(logger, args.log_path)
    try:
        run(args.interval, args.db_path)
    except AlreadyRunningError:
        # 콘솔 없는 환경에서는 stderr도 None일 수 있어 raw traceback이 오히려 또
        # 다른 크래시가 되니, 로그로만 남긴다.
        logger.exception("시작하지 못했습니다.")
        sys.exit(EXIT_ALREADY_RUNNING)


if __name__ == "__main__":
    main()
