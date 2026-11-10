from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo

import pytest
from goals import GoalStore, days_between, goals_for_day, period_target_minutes


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(tmp_path, clock):
    with GoalStore(tmp_path / "goals.db", now=clock) as opened:
        yield opened


def _make(store, name, minutes, weekdays, process):
    return store.create(name=name, daily_target_minutes=minutes, weekdays=weekdays, processes=[process], sites=[])


def _week(first: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range(7)]


MONDAY = date(2026, 11, 9)  # 월요일(weekday 0)


# --- 구간이 걸치는 날짜 ---


def test_days_between_treats_the_end_as_the_next_periods_start() -> None:
    kst = timezone(timedelta(hours=9))
    start = datetime(2026, 11, 9, tzinfo=kst)

    assert days_between(start, datetime(2026, 11, 10, tzinfo=kst), kst) == [MONDAY]  # 일
    assert days_between(start, datetime(2026, 11, 16, tzinfo=kst), kst) == _week(MONDAY)  # 주
    assert len(days_between(datetime(2026, 11, 1, tzinfo=kst), datetime(2026, 12, 1, tzinfo=kst), kst)) == 30  # 월


def test_days_between_uses_the_given_timezone_not_utc() -> None:
    """한국 자정(전날 15:00Z)에 시작하는 구간이 UTC 날짜로 하루 어긋나면 목표량이 전날 요일로 계산된다."""
    kst = timezone(timedelta(hours=9))
    start = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)  # = 11월 9일 00:00 KST
    end = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)

    assert days_between(start, end, kst) == [MONDAY]
    assert days_between(start, end, UTC) == [date(2026, 11, 8), MONDAY]  # UTC로 보면 두 날에 걸친다


class _SpringForward(tzinfo):
    """2026-03-08 03:00(로컬)부터 한 시간 앞당겨지는(UTC-5 → UTC-4) 서머타임 흉내. 이 날은 23시간이다(Windows에는 시간대 데이터베이스가 없을 수 있어 직접 만든다)."""

    def utcoffset(self, dt):
        return timedelta(hours=-4) if dt.replace(tzinfo=None) >= datetime(2026, 3, 8, 3, 0) else timedelta(hours=-5)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "TEST"


def test_days_between_handles_a_day_that_is_not_24_hours() -> None:
    """서머타임 전환일은 23시간이다. 날짜 연산이라 시간 길이와 무관하게 하루로 센다."""
    tz = _SpringForward()
    day = datetime(2026, 3, 8, tzinfo=tz)

    # 이 시간대에서 그날이 정말 23시간이다(같은 tzinfo끼리의 뺄셈은 벽시계 차이라서 UTC로 바꿔 잰다)
    assert (datetime(2026, 3, 9, tzinfo=tz).astimezone(UTC) - day.astimezone(UTC)).total_seconds() == 23 * 3600
    assert days_between(day, datetime(2026, 3, 9, tzinfo=tz), tz) == [date(2026, 3, 8)]
    assert len(days_between(datetime(2026, 3, 2, tzinfo=tz), datetime(2026, 3, 9, tzinfo=tz), tz)) == 7  # 그 날이 낀 한 주


def test_an_end_that_is_not_after_the_start_means_that_one_day() -> None:
    start = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)

    assert days_between(start, start, UTC) == [MONDAY]
    assert days_between(start, start - timedelta(hours=1), UTC) == [MONDAY]


def test_days_between_defaults_to_this_pcs_timezone() -> None:
    start = datetime(2026, 11, 9).astimezone()  # 이 PC의 시간대의 11월 9일 자정
    end = datetime(2026, 11, 10).astimezone()

    assert days_between(start, end) == [MONDAY]


# --- 목표량 ---


def test_the_target_adds_the_daily_target_of_every_day_the_goal_applies(store) -> None:
    weekday_goal = _make(store, "평일", 60, [0, 1, 2, 3, 4], "Code.exe")
    weekend_goal = _make(store, "주말", 30, [5, 6], "Zoom.exe")

    targets = period_target_minutes(store, _week(MONDAY))

    assert targets == {weekday_goal.id: 5 * 60, weekend_goal.id: 2 * 30}


def test_one_day_counts_only_if_the_goal_applies_that_weekday(store) -> None:
    goal = _make(store, "월요일만", 45, [0], "Code.exe")

    assert period_target_minutes(store, [MONDAY]) == {goal.id: 45}
    assert period_target_minutes(store, [MONDAY + timedelta(days=1)]) == {goal.id: 0}  # 화요일은 쉬는 날


def test_a_goal_with_no_applicable_day_in_the_period_has_zero_target_not_a_missing_entry(store) -> None:
    goal = _make(store, "주말", 30, [5, 6], "Zoom.exe")

    assert period_target_minutes(store, [MONDAY]) == {goal.id: 0}


def test_a_day_with_a_snapshot_uses_the_snapshot_even_if_the_goal_changed_later(store, clock) -> None:
    """지난 날의 목표량이 목표를 고친 뒤에 바뀌면 지난 주 달성률이 소급해서 달라진다."""
    goal = _make(store, "공부", 60, [0, 1, 2, 3, 4, 5, 6], "Code.exe")
    clock.now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    store.snapshot_today(MONDAY)  # 월요일의 목표량은 60으로 굳는다
    store.update(goal.id, name="공부", daily_target_minutes=120, weekdays=[0, 1, 2, 3, 4, 5, 6], processes=["Code.exe"], sites=[])

    targets = period_target_minutes(store, [MONDAY, MONDAY + timedelta(days=1)])

    assert targets == {goal.id: 60 + 120}  # 월요일은 스냅샷(60), 화요일은 지금 설정(120)


def test_a_snapshot_of_a_weekday_the_goal_no_longer_uses_still_counts_for_that_day(store, clock) -> None:
    goal = _make(store, "월요일만", 60, [0], "Code.exe")
    clock.now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    store.snapshot_today(MONDAY)
    store.update(goal.id, name="월요일만", daily_target_minutes=60, weekdays=[4], processes=["Code.exe"], sites=[])  # 이제 금요일만

    assert period_target_minutes(store, [MONDAY])[goal.id] == 60  # 그날은 월요일 목표였다


def test_a_deleted_goals_old_snapshot_is_not_counted(store, clock) -> None:
    kept = _make(store, "남김", 30, [0], "Code.exe")
    gone = _make(store, "지움", 90, [0], "Zoom.exe")
    clock.now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    store.snapshot_today(MONDAY)
    store.delete(gone.id)

    targets = period_target_minutes(store, [MONDAY])

    assert targets == {kept.id: 30}  # 지운 목표는 화면에 없으므로 목표량에도 없다


def test_no_goals_or_no_days_give_nothing(store) -> None:
    assert period_target_minutes(store, _week(MONDAY)) == {}
    goal = _make(store, "공부", 60, [0], "Code.exe")
    assert period_target_minutes(store, []) == {goal.id: 0}


def test_goals_for_day_picks_the_goals_that_apply_that_weekday(store) -> None:
    goal = _make(store, "월", 10, [0], "Code.exe")

    assert [g.id for g in goals_for_day(store, MONDAY, store.list_goals())] == [goal.id]
    assert goals_for_day(store, MONDAY + timedelta(days=1), store.list_goals()) == []


def test_midnight_boundaries_are_the_callers_timezone(store) -> None:
    """한국 사용자의 월요일 00:00(일요일 15:00Z)에 시작한 하루 구간은 월요일의 목표량이어야 한다."""
    goal = _make(store, "월요일만", 45, [0], "Code.exe")
    kst = timezone(timedelta(hours=9))
    start = datetime(2026, 11, 9, tzinfo=kst)

    days = days_between(start, start + timedelta(days=1), kst)

    assert period_target_minutes(store, days) == {goal.id: 45}
    assert time(0) == start.timetz().replace(tzinfo=None)
