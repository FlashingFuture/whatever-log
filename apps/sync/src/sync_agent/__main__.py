"""로그인한 사용자의 목표와 날짜별 달성 분을 서버와 맞추는 에이전트.

hub와 별개의 프로세스다(화면·hub 없이 혼자 돈다 — docs/sync-design.md). 일정 간격으로 `goalsync.sync_once`를 부른다.
로그인하지 않았거나 사용자가 아직 확인 창에서 동기화를 켜지 않았다면 아무것도 하지 않고 기다린다. 서버에 닿지 못해도
기록·집계에는 영향이 없고, 다음 주기에 다시 시도한다(연속으로 실패하면 간격을 늘린다).

로그인은 이 프로그램이 아니라 화면(또는 `python -m cloud login`)에서 한다. 토큰은 Windows 자격 증명 관리자에서 읽는다.
컨테이너·시험 서버처럼 자격 증명 관리자가 없는 환경에서는 `--token-from-env`로 환경 변수(`WHATEVER_LOG_TOKEN`)를 읽는다.

사용법:
    uv run python -m sync_agent                 # 5분마다 계속
    uv run python -m sync_agent --once          # 한 번만 하고 끝(시험·수동 실행)
    uv run python -m sync_agent --token-from-env --once   # 환경 변수 토큰으로(자격 증명 관리자 없이)
"""

import argparse
import logging
import math
import sys
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from cloud import (
    Account,
    EnvTokenStore,
    KeyringTokenStore,
    NotAuthorized,
    ServerApi,
    ServerError,
    ServerUnreachable,
    TokenStore,
    load_config,
)
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from goals import GoalStore, SchemaVersionError
from goalsync import SyncReport, SyncState, sync_once
from recorder.__main__ import DEFAULT_DB_PATH as DEFAULT_RECORDER_DB
from supervision.lock import AlreadyRunningError, acquire_lock
from supervision.log_setup import configure_logging

DEFAULT_INTERVAL_SECONDS = 300.0
MIN_INTERVAL_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 3600.0

_APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_STATE_PATH = _APP_DIR / "sync.db"
DEFAULT_LOG_PATH = _APP_DIR / "sync.log"
# hub와 같은 목표 DB를 쓴다(apps/hub/goals.db). 둘 다 WAL 모드이고 쓰기는 BEGIN IMMEDIATE로 직렬화된다.
DEFAULT_GOALS_DB = _APP_DIR.parent / "hub" / "goals.db"

logger = logging.getLogger("sync_agent")


def _interval_type(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}'는 숫자가 아닙니다.") from exc
    if not math.isfinite(parsed) or parsed < MIN_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(f"주기는 {MIN_INTERVAL_SECONDS}초 이상의 유한한 숫자여야 합니다.")
    return parsed


def run_cycle(
    token_store: TokenStore,
    *,
    goals_db: Path,
    state_db: Path,
    recorder_db: Path,
    server_url: str,
    today: Callable[[], date] = lambda: datetime.now().astimezone().date(),
    api_factory: Callable[[str, str], object] = lambda url, token: ServerApi(url, token),
) -> SyncReport | None:
    """한 주기. 로그인되어 있지 않으면 None. 서버에 닿지 못하면 ServerUnreachable, 토큰이 거부되면 NotAuthorized를 올린다."""
    session = Account(token_store).session()
    if session is None:
        return None
    with GoalStore(goals_db) as store, SyncState(state_db) as state:
        return sync_once(
            store,
            state,
            api_factory(server_url, session.token),
            recorder_db,
            email=session.email,
            today=today(),
        )


def _describe(report: SyncReport) -> str:
    """로그에 남길 한 줄 요약(목표 이름·프로세스 같은 내용은 담지 않는다)."""
    if report.skipped:
        return f"건너뜀({report.skipped})"
    return (
        f"올림 {report.created}, 수정 {report.pushed}, 삭제 {report.deleted}, 반영 {report.pulled}, "
        f"연결 끊김 {report.unlinked}, 달성도 {report.progress_sent}줄, 문제 {len(report.problems)}건"
    )


def main(argv: list[str] | None = None, *, sleep: Callable[[float], None] = time.sleep) -> int:
    """에이전트를 실행한다(--once가 아니면 계속 돈다). 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="whatever.log 동기화 에이전트")
    parser.add_argument("--interval", type=_interval_type, default=DEFAULT_INTERVAL_SECONDS, help="동기화 주기(초)")
    parser.add_argument("--once", action="store_true", help="한 번만 하고 끝낸다")
    parser.add_argument("--token-from-env", action="store_true", help="자격 증명 관리자 대신 환경 변수 WHATEVER_LOG_TOKEN의 토큰을 쓴다")
    parser.add_argument("--goals-db", type=Path, default=DEFAULT_GOALS_DB)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_RECORDER_DB, help="recorder.db 경로")
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_ARGUMENT_ERROR if exit_.code else 0

    configure_logging(logger, args.log_path)
    try:
        config = load_config()
    except ValueError as error:
        logger.error("서버 설정이 올바르지 않습니다: %s", error)
        return EXIT_ARGUMENT_ERROR

    try:
        lock = acquire_lock(args.state_db.with_suffix(".lock"))
    except AlreadyRunningError:
        logger.exception("시작하지 못했습니다.")
        return EXIT_ALREADY_RUNNING

    token_store: TokenStore = EnvTokenStore() if args.token_from_env else KeyringTokenStore()
    failures = 0
    try:
        while True:
            try:
                report = run_cycle(
                    token_store,
                    goals_db=args.goals_db,
                    state_db=args.state_db,
                    recorder_db=args.db_path,
                    server_url=config.server_url,
                )
                failures = 0
                logger.info("동기화: %s", "로그인되어 있지 않아 건너뜀" if report is None else _describe(report))
                if report is not None:
                    for problem in report.problems:
                        logger.warning("동기화 문제: %s", problem)
            except ServerUnreachable:
                failures += 1
                logger.warning("서버에 닿지 못했습니다. 다음 주기에 다시 시도합니다(연속 %d회).", failures)
            except NotAuthorized:
                failures += 1
                logger.warning("로그인이 만료되었거나 취소되었습니다. 다시 로그인해 주세요.")
            except ServerError as error:
                failures += 1
                logger.error("서버 오류(%s, %s): %s", error.status, error.code, error.message)
            except SchemaVersionError as error:
                logger.error("%s", error)
                return 1  # 더 새 프로그램이 만든 DB — 다시 시도해도 같다
            except Exception:  # 한 주기의 예상 못 한 오류가 에이전트를 죽이지 않게(다음 주기에 다시)
                failures += 1
                logger.exception("동기화 중 예상하지 못한 오류가 났습니다.")
            if args.once:
                return 0 if failures == 0 else 1
            # 연속 실패가 늘수록 간격을 두 배씩 늘린다(서버가 죽어 있을 때 계속 두드리지 않게).
            sleep(min(args.interval * (2 ** min(failures, 6)), MAX_BACKOFF_SECONDS) if failures else args.interval)
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
