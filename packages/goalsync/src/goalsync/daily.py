"""날짜별 달성 분 계산: recorder.db의 틱에서 목표마다 "그날 연결한 프로세스·사이트의 활성 시간 합"을 분으로 뽑는다.

수행 시간의 정의는 `goals.compute_progress`가 갖고 있고 여기서는 그것을 날짜 단위로 호출할 뿐이다(화면의 요약과 서버에 올라가는
수치가 같은 뜻이 되게). 하루의 경계는 이 PC의 **로컬 시간대** 자정이다.

그날의 목표 설정은 하루 스냅샷(`GoalStore.snapshots`)이 있으면 그것을(목표를 나중에 바꿔도 지난 날이 바뀌지 않게), 없으면
지금의 목표를 쓴다. 서버가 아는 것은 목표 이름·분뿐이고, 어떤 프로세스에서 나온 시간인지는 여기서 계산하고 버린다.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from aggregation.range import site_usage_by_range, usage_by_range
from goals import GoalStore, compute_progress, goals_for_day

MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class DayEntry:
    """(이 PC 목표, 날짜)의 달성 분과 그날의 목표 분."""

    goal_id: int
    day: str
    minutes: int
    target_minutes: int


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """로컬 시간대의 하루 [자정, 다음 날 자정)을 UTC 시각으로. 서머타임 날도 다음 날 자정을 직접 구한다."""
    start = datetime.combine(day, time.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return start.astimezone(UTC), end.astimezone(UTC)


def _open_recorder(path: Path) -> sqlite3.Connection:
    """recorder.db를 읽기 전용으로 연다(recorder가 쓰는 도중에도 안전하다 — WAL)."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _is_missing_site_schema(error: sqlite3.OperationalError) -> bool:
    message = str(error)
    return "no such table: sites" in message or "foreground_site_id" in message


def day_entries(
    store: GoalStore,
    recorder_db: Path,
    days: list[date],
    *,
    only_goal_ids: set[int] | None = None,
) -> list[DayEntry]:
    """days 각각에 대해 목표별 달성 분을 계산한다. only_goal_ids가 있으면 그 목표만 돌려준다.

    그날 요일에 적용되지 않는 목표(스냅샷에 없고 요일이 아닌 목표)는, 달성 분이 0이면 줄을 만들지 않는다 — 쉬는 날의
    빈 줄을 서버에 쌓지 않으려는 것이다. 분은 활성 초를 반올림해 0~1440으로 자른다.
    """
    current = store.list_goals()
    entries: list[DayEntry] = []
    conn = _open_recorder(recorder_db)
    try:
        for day in days:
            start, end = local_day_bounds(day)
            applicable = goals_for_day(store, day, current)
            # 그날 적용되지 않는 목표도 시간이 있으면 보내려고, 계산 대상은 "지금 목표 전부 + 그날 적용 목표"의 합집합이다.
            by_id = {goal.id: goal for goal in applicable}
            for goal in current:
                by_id.setdefault(goal.id, goal)
            goals = list(by_id.values())
            usage = usage_by_range(conn, start, end)
            site_usage: dict[str, list] = {}
            for browser in {site.browser for goal in goals for site in goal.sites}:
                try:
                    site_usage[browser] = site_usage_by_range(conn, browser, start, end)["by_site"]
                except sqlite3.OperationalError as error:
                    if not _is_missing_site_schema(error):
                        raise
                    site_usage[browser] = []
            active = {row["process"]: row["active_seconds"] for row in usage["by_process"]}
            active_sites = {
                (browser, row["domain"]): row["active_seconds"] for browser, rows in site_usage.items() for row in rows
            }
            progress, _ = compute_progress(goals, active, active_sites)
            applied = set(by_id) & {goal.id for goal in applicable}
            for item in progress:
                if only_goal_ids is not None and item.goal_id not in only_goal_ids:
                    continue
                minutes = min(MINUTES_PER_DAY, max(0, round(item.active_seconds / 60)))
                if item.goal_id not in applied and minutes == 0:
                    continue
                target = by_id[item.goal_id].daily_target_minutes
                entries.append(DayEntry(item.goal_id, day.isoformat(), minutes, target))
    finally:
        conn.close()
    return entries


def recent_days(today: date, count: int) -> list[date]:
    """오늘을 포함해 최근 count일(오래된 날부터)."""
    return [today - timedelta(days=offset) for offset in range(count - 1, -1, -1)]


Clock = Callable[[], datetime]
