"""로그인한 사용자의 목표와 날짜별 달성 분을 서버와 맞추는 에이전트.

hub와 별개의 프로세스다(화면·hub 없이 혼자 돈다 — docs/sync-client.md). 일정 간격으로 `goalsync.sync_once`를 부른다.
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
from common.paths import data_path
from goals import META_DEVICE_ID, GoalStore, SchemaVersionError, StaleSyncError
from goals import sync_status as status
from goalsync import SyncReport, SyncState, sync_once
from recorder.__main__ import DEFAULT_DB_PATH as DEFAULT_RECORDER_DB
from supervision.lock import AlreadyRunningError, acquire_lock
from supervision.log_setup import configure_logging

DEFAULT_INTERVAL_SECONDS = 300.0
MIN_INTERVAL_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 3600.0

_APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_STATE_PATH = data_path(_APP_DIR, "sync.db")
DEFAULT_LOG_PATH = data_path(_APP_DIR, "sync.log", subdir="logs")
# hub와 같은 목표 DB를 쓴다(apps/hub/goals.db). 둘 다 WAL 모드이고 쓰기는 BEGIN IMMEDIATE로 직렬화된다.
DEFAULT_GOALS_DB = data_path(_APP_DIR.parent / "hub", "goals.db")

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


def _result_of(report: SyncReport | None) -> str:
    """한 주기의 결과를 상태 종류로(건너뜀도 오류는 아니다)."""
    if report is None:
        return status.RESULT_SIGNED_OUT
    if report.skipped == "not_enabled":
        return status.RESULT_NOT_ENABLED
    if report.skipped == "account_changed":
        return status.RESULT_ACCOUNT_CHANGED
    return status.RESULT_OK


def next_delay(interval: float, failures: int) -> float:
    """다음 주기까지 기다릴 시간(초). 연속 실패가 늘수록 두 배씩 늘려(서버가 죽어 있을 때 계속 두드리지 않게) 최대 1시간까지.

    상태에 적는 "주기"도 이 값이다 — 화면이 "에이전트가 멈췄다"를 판단하는 기준이 실제로 자는 시간보다 짧으면, 백오프 중인 멀쩡한
    에이전트가 멈춘 것으로 보인다.
    """
    if failures == 0:
        return interval
    return min(interval * (2 ** min(failures, 6)), MAX_BACKOFF_SECONDS)


def record_status(
    goals_db: Path,
    *,
    result: str,
    problems: int,
    interval: float,
    expect_generation: int | None = None,
) -> None:
    """화면이 보여 줄 상태를 적고, 이 PC의 기기 ID도 함께 알린다. 상태를 못 적어도 동기화를 멈추지 않는다(상태는 알림일 뿐이다).

    expect_generation이 있으면 그 주기가 시작한 뒤 계정이 정리되었을 때 적지 않는다(낡은 주기의 성공이 새 계정의 상태로 남지 않게).
    """
    if expect_generation is None:
        # 주기를 시작할 때 세대를 읽지 못했다. 동기화는 계속하지만, 그 사이 계정이 정리됐는지 확인할 수 없으니 이번 주기의 상태는 적지 않는다
        # (이전 계정의 결과가 새 계정의 상태로 남지 않게).
        logger.info("동기화 세대를 읽지 못해 이번 주기의 상태는 기록하지 않았습니다.")
        return
    try:
        with GoalStore(goals_db) as store:
            status.record(store, result=result, problems=problems, interval=interval, expect_generation=expect_generation)
    except StaleSyncError:
        logger.info("동기화 도중 계정이 정리되어 이번 주기의 상태는 기록하지 않았습니다.")
    except Exception:  # DB가 잠겼거나 더 새 버전이어도 에이전트는 계속 돈다
        logger.warning("동기화 상태를 기록하지 못했습니다.")


def current_generation(goals_db: Path) -> int | None:
    """주기를 시작하기 전의 동기화 세대. 읽지 못하면 None(그러면 이번 주기의 상태는 적지 않는다 — 계정이 정리됐는지 확인할 수 없다)."""
    try:
        with GoalStore(goals_db) as store:
            return store.generation()
    except Exception:
        return None


def publish_device_id(goals_db: Path, state_db: Path) -> None:
    """이 PC의 기기 ID(sync.db)를 `goals.db`에도 적어 둔다. hub가 "이 기기"를 알아보는 데 쓴다 — hub와 에이전트가 이미 같은 goals.db를
    공유하므로, 상태 DB 경로를 따로 맞추지 않아도(맞추는 것을 잊어도) 이 기기를 지우게 되는 일이 없다."""
    try:
        with SyncState(state_db) as state, GoalStore(goals_db) as store:
            device_id = state.device_id()
            if store.get_meta(META_DEVICE_ID) != device_id:
                store.set_meta(META_DEVICE_ID, device_id)
    except Exception:
        logger.warning("기기 ID를 알리지 못했습니다.")


def _describe(report: SyncReport) -> str:
    """로그에 남길 한 줄 요약(목표 이름·프로세스 같은 내용은 담지 않는다 — 문제는 건수만 센다)."""
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
            # 이 주기가 시작할 때의 세대와, 이 PC의 기기 ID를 먼저 알린다. 세대는 성공·실패를 가리지 않고 이 주기의 모든 상태 기록에
            # 쓴다(주기 도중 계정이 정리되면 이 주기의 결과는 어떤 것이든 낡은 것이다). 기기 ID를 주기 전에 알리는 이유는, 이 주기가
            # 달성도를 보내 서버에 이 기기의 줄이 생기기 전에 hub가 이 기기를 알아볼 수 있게 하려는 것이다.
            publish_device_id(args.goals_db, args.state_db)
            generation = current_generation(args.goals_db)
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
                record_status(
                    args.goals_db,
                    result=_result_of(report),
                    problems=0 if report is None else len(report.problems),
                    interval=args.interval,
                    expect_generation=generation,
                )
                # 문제의 문장에는 목표 이름이 들어 있을 수 있다("'공부': 서버에 같은 이름의…"). 로그에는 건수만 남긴다(위 요약).
            except ServerUnreachable:
                failures += 1
                logger.warning("서버에 닿지 못했습니다. 다음 주기에 다시 시도합니다(연속 %d회).", failures)
                record_status(
                    args.goals_db,
                    result=status.RESULT_UNREACHABLE,
                    problems=0,
                    interval=next_delay(args.interval, failures),
                    expect_generation=generation,
                )
            except NotAuthorized:
                failures += 1
                logger.warning("로그인이 만료되었거나 취소되었습니다. 다시 로그인해 주세요.")
                record_status(
                    args.goals_db,
                    result=status.RESULT_NOT_AUTHORIZED,
                    problems=0,
                    interval=next_delay(args.interval, failures),
                    expect_generation=generation,
                )
            except ServerError as error:
                failures += 1
                logger.error("서버 오류(%s, %s): %s", error.status, error.code, error.message)
                record_status(
                    args.goals_db,
                    result=status.RESULT_SERVER_ERROR,
                    problems=0,
                    interval=next_delay(args.interval, failures),
                    expect_generation=generation,
                )
            except SchemaVersionError as error:
                logger.error("%s", error)
                return 1  # 더 새 프로그램이 만든 DB — 다시 시도해도 같다
            except Exception:  # 한 주기의 예상 못 한 오류가 에이전트를 죽이지 않게(다음 주기에 다시)
                failures += 1
                logger.exception("동기화 중 예상하지 못한 오류가 났습니다.")
                record_status(
                    args.goals_db,
                    result=status.RESULT_INTERNAL,
                    problems=0,
                    interval=next_delay(args.interval, failures),
                    expect_generation=generation,
                )
            if args.once:
                return 0 if failures == 0 else 1
            sleep(next_delay(args.interval, failures))
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
