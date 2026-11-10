"""구간의 목표량 — 달성률(수행 시간 ÷ 목표량)의 분모. "그날 어떤 목표가 몇 분이었나"의 유일한 원본.

정의:
- 하루의 목표 설정 = 그날의 스냅샷이 있으면 그것(목표를 나중에 바꿔도 지난 날이 바뀌지 않는다), 없으면 지금 목표 중
  그 요일(월=0 … 일=6)에 적용되는 것. 서버로 올리는 날짜별 달성(`goalsync.daily`)과 같은 규칙이다.
- 구간의 목표량(분) = 구간의 각 날짜에 그날 적용된 목표의 하루 목표 분을 더한 것. 쉬는 요일(목표를 적용하지 않는 요일)은 더하지 않는다.
  아직 오지 않은 날(이번 주의 남은 날)도 그 요일에 적용되는 목표라면 더한다 — 구간 전체의 목표에 얼마나 다가갔는지를 보여 준다.
- 달성률 = 수행 시간 ÷ 구간의 목표량. 목표량이 0이면(구간에 적용되는 날이 없다) 달성률은 없다. 100%를 넘을 수 있다.

날짜의 경계는 이 PC의 로컬 시간대 자정이다(구간을 정하는 화면과 같은 시계).
"""

from collections.abc import Sequence
from datetime import date, datetime, timedelta, tzinfo

from goals.models import Goal
from goals.store import GoalStore


def goals_for_day(store: GoalStore, day: date, current: Sequence[Goal]) -> list[Goal]:
    """그날 적용된 목표 설정. 스냅샷이 있으면 스냅샷, 없으면 지금 목표 중 그 요일에 적용되는 것."""
    snapshots = store.snapshots(day)
    if snapshots:
        return [
            Goal(
                id=snap.goal_id,
                name=snap.name,
                daily_target_minutes=snap.daily_target_minutes,
                weekdays=frozenset(range(7)),
                processes=snap.processes,
                created_at="",
                updated_at="",
                sites=snap.sites,
            )
            for snap in snapshots
        ]
    return [goal for goal in current if day.weekday() in goal.weekdays]


def days_between(start: datetime, end: datetime, tz: tzinfo | None = None) -> list[date]:
    """구간 [start, end)이 걸치는 날짜들(tz 기준, 기본은 이 PC의 시간대). 시각에는 타임존이 있어야 한다.

    끝은 포함하지 않는다 — 자정에 끝나는 구간은 마지막 날이 하루 전이다. 끝이 시작보다 앞서거나 같으면 시작한 날 하루로 본다.
    """
    first = start.astimezone(tz).date()
    last = (end - timedelta(microseconds=1)).astimezone(tz).date() if end > start else first
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def period_target_minutes(store: GoalStore, days: Sequence[date]) -> dict[int, int]:
    """지금 있는 목표마다의 구간 목표량(분). 구간에 한 번도 적용되지 않은 목표는 0이다.

    지금 없는 목표(지운 목표)의 지난 스냅샷은 세지 않는다 — 화면이 보여 주는 목표는 지금 있는 것뿐이다.
    """
    current = store.list_goals()
    totals = {goal.id: 0 for goal in current}
    for day in days:
        for goal in goals_for_day(store, day, current):
            if goal.id in totals:
                totals[goal.id] += goal.daily_target_minutes
    return totals
