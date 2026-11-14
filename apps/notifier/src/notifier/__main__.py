"""알림 에이전트: 목표의 알림 규칙을 주기적으로 확인해 마감 시각까지 하지 않았으면 Windows 알림을 띄운다 (docs/goal-management.md).

hub·창과 별개의 프로세스다(창이 닫혀 있어도 알림이 가야 하므로). 일정 간격으로 goals.db의 알림 규칙을 읽고, 규칙이 있을 때만 recorder.db(읽기
전용)에서 오늘의 활성 시간을 재서 `goals.due_alerts`로 알릴 것을 가린다. **판단과 알림은 모두 이 PC 안에서 끝난다** — 서버를 부르지 않고 프로세스·
목표 이름이 PC 밖으로 나가지 않는다(그래서 로그인하지 않아도 동작한다).

같은 규칙은 하루에 한 번만 알린다. 알림을 띄우기 **전에** "오늘 알렸다"를 적는다 — 적은 뒤 알림이 실패하면 그날은 알리지 못하지만, 반대로(알린 뒤 적기)
하면 적기 전에 죽었을 때 같은 알림이 반복될 수 있다. 알림은 부가 기능이라 하나를 놓치는 쪽이 덜 해롭다.

사용법:
    uv run python -m notifier                # 1분마다 계속
    uv run python -m notifier --once         # 한 번만 확인하고 끝(시험·수동 실행)
    uv run python -m notifier --test         # 알림이 뜨는지 확인하는 시험 알림 하나를 띄우고 끝
"""

import argparse
import logging
import math
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from aggregation.range import site_usage_by_range, usage_by_range
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from common.memory import keep_trimmed
from common.paths import data_path
from goals import DueAlert, GoalStore, SchemaVersionError, compute_progress, due_alerts
from recorder.__main__ import DEFAULT_DB_PATH as DEFAULT_RECORDER_DB
from supervision.heartbeat import beat
from supervision.lock import AlreadyRunningError, acquire_lock
from supervision.log_setup import configure_logging

from notifier.toast import show_toast

DEFAULT_INTERVAL_SECONDS = 60.0
MIN_INTERVAL_SECONDS = 5.0

_APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOCK_PATH = data_path(_APP_DIR, "notifier.lock")
DEFAULT_LOG_PATH = data_path(_APP_DIR, "notifier.log", subdir="logs")
# hub와 같은 목표 DB를 쓴다(apps/hub/goals.db). 둘 다 WAL 모드이고 쓰기는 BEGIN IMMEDIATE로 직렬화된다.
DEFAULT_GOALS_DB = data_path(_APP_DIR.parent / "hub", "goals.db")

logger = logging.getLogger("notifier")

Notify = Callable[[str, str], bool]


def _interval_type(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}'는 숫자가 아닙니다.") from exc
    if not math.isfinite(parsed) or parsed < MIN_INTERVAL_SECONDS:
        raise argparse.ArgumentTypeError(f"주기는 {MIN_INTERVAL_SECONDS}초 이상의 유한한 숫자여야 합니다.")
    return parsed


def _is_missing_site_schema(error: sqlite3.OperationalError) -> bool:
    """사이트 테이블/컬럼이 생기기 전의 옛 DB에서 난 오류인지(다른 DB 오류와 구분)."""
    message = str(error)
    return "no such table: sites" in message or "foreground_site_id" in message


def describe(due: DueAlert) -> tuple[str, str]:
    """알림의 제목과 본문. 목표 이름·프로세스 이름은 이 PC 안에서만 쓰인다(서버로 가지 않는다)."""
    alert = due.alert
    subject = f"'{due.goal_name}'" if alert.target_process is None else alert.target_process
    return (
        "whatever.log",
        f"{subject}: 오늘 {alert.deadline}까지 {alert.min_minutes}분을 채우지 못했어요 (지금 {due.active_minutes}분).",
    )


def measure_today(
    recorder_db: Path, goals: list, *, now: datetime
) -> tuple[dict[str, float], dict[int, float]]:
    """오늘(이 PC의 시간대 자정부터 지금까지)의 프로세스별 활성 시간(초)과 목표별 수행 시간(초). 수행 시간의 정의는 `goals.compute_progress`다."""
    local_midnight = datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo)
    start, end = local_midnight.astimezone(UTC), now.astimezone(UTC)
    conn = sqlite3.connect(f"{recorder_db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        usage = usage_by_range(conn, start, end)
        site_usage: dict[str, list] = {}
        for browser in {site.browser for goal in goals for site in goal.sites}:
            try:
                site_usage[browser] = site_usage_by_range(conn, browser, start, end)["by_site"]
            except sqlite3.OperationalError as error:
                if not _is_missing_site_schema(error):
                    raise
                site_usage[browser] = []
    finally:
        conn.close()
    by_process = {row["process"]: row["active_seconds"] for row in usage["by_process"]}
    by_site = {(browser, row["domain"]): row["active_seconds"] for browser, rows in site_usage.items() for row in rows}
    progress, _ = compute_progress(goals, by_process, by_site)
    return by_process, {item.goal_id: item.active_seconds for item in progress}


def check_once(goals_db: Path, recorder_db: Path, *, now: datetime, notify: Notify = show_toast) -> int:
    """알림 규칙을 한 번 확인하고 알린 개수를 돌려준다. 켜진 규칙이 없으면 기록 DB를 열지 않는다.

    now는 이 PC의 시간대가 붙은 지금이다(시험이 시계를 고정할 수 있게 주입한다).
    """
    with GoalStore(goals_db) as store:
        alerts = [alert for alert in store.list_alerts() if alert.enabled]
        if not alerts:
            return 0
        day: date = now.date()
        fired = store.fired_alert_ids(day)
        if all(alert.id in fired for alert in alerts):
            return 0
        goals = store.list_goals()
        try:
            by_process, goal_seconds = measure_today(recorder_db, goals, now=now)
        except sqlite3.Error:
            logger.warning("기록 DB를 읽지 못해 이번 확인은 건너뜁니다.", exc_info=True)
            return 0
        sent = 0
        for due in due_alerts(
            alerts,
            goals,
            now=now,
            seconds_by_process=by_process,
            goal_seconds=goal_seconds,
            already_fired=fired,
        ):
            if not store.mark_alert_fired(due.alert.id, day, due.alert):
                continue  # 다른 곳에서 먼저 알렸거나, 그새 규칙이 지워지거나 바뀌었다(다음 확인에서 바뀐 규칙으로 다시 평가한다)
            title, body = describe(due)
            if notify(title, body):
                sent += 1
                logger.info("알림을 띄웠습니다(규칙 %d).", due.alert.id)
            else:
                logger.warning("알림을 띄우지 못했습니다(규칙 %d). 오늘은 다시 알리지 않습니다.", due.alert.id)
        return sent


def main(
    argv: list[str] | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    notify: Notify = show_toast,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
) -> int:
    """에이전트를 실행한다(--once·--test가 아니면 계속 돈다). 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(
        description="whatever.log 알림 에이전트",
        # `--inter 600` 같은 축약을 받으면 supervisor(정확한 `--interval`만 읽는다)와 주기를 다르게 읽어 박동 허용 시간이 어긋난다
        allow_abbrev=False,
    )
    parser.add_argument("--interval", type=_interval_type, default=DEFAULT_INTERVAL_SECONDS, help="확인 주기(초)")
    parser.add_argument("--once", action="store_true", help="한 번만 확인하고 끝낸다")
    parser.add_argument("--test", action="store_true", help="시험 알림 하나를 띄우고 끝낸다")
    parser.add_argument("--goals-db", type=Path, default=DEFAULT_GOALS_DB)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_RECORDER_DB, help="recorder.db 경로")
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_ARGUMENT_ERROR if exit_.code else 0

    configure_logging(logger, args.log_path)
    if args.test:
        ok = notify("whatever.log", "알림이 잘 보이나요? 이 알림은 시험용이에요.")
        return 0 if ok else 1

    keep_trimmed()  # 쉬는 시간이 긴 백그라운드 프로세스 — 안 쓰는 물리 메모리를 돌려준다(common.memory)
    try:
        lock = acquire_lock(args.lock_path)
    except AlreadyRunningError:
        logger.exception("시작하지 못했습니다.")
        return EXIT_ALREADY_RUNNING

    try:
        while True:
            beat()  # supervisor에게 "살아서 돌고 있다"를 알린다(멈추면 supervisor가 다시 띄운다). 확인이 실패해도 돌고 있으니 결과와 무관하게 낸다
            try:
                check_once(args.goals_db, args.db_path, now=clock(), notify=notify)
            except SchemaVersionError as error:
                logger.error("%s", error)
                return 1  # 더 새 프로그램이 만든 DB — 다시 시도해도 같다
            except Exception:  # 한 번의 예상 못 한 오류가 에이전트를 죽이지 않게(다음 주기에 다시)
                logger.exception("알림을 확인하는 중 예상하지 못한 오류가 났습니다.")
            beat()
            if args.once:
                return 0
            sleep(args.interval)
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
