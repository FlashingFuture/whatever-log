import sqlite3
from datetime import UTC, date, datetime

import pytest

from goals import (
    Goal,
    GoalNotFoundError,
    GoalStore,
    GoalValidationError,
    compute_progress_per_goal,
    due_alerts,
    goals_for_day,
    period_target_minutes,
    period_window,
)
from goals.store import SCHEMA_VERSION

TODAY = date(2026, 11, 5)  # 목요일
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
LOCAL = datetime.now().astimezone().tzinfo


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def store(tmp_path):
    with GoalStore(tmp_path / "goals.db", now=_Clock()) as opened:
        yield opened


def _make(store, name="공부", **overrides):
    fields = {
        "name": name,
        "daily_target_minutes": 60,
        "weekdays": ALL_DAYS,
        "processes": [],
        "today": TODAY,
    }
    fields.update(overrides)
    return store.create(**fields)


def _errors(call):
    with pytest.raises(GoalValidationError) as caught:
        call()
    return {error.field: error.code for error in caught.value.errors}


def _goal(**overrides) -> Goal:
    fields = {
        "id": 1,
        "name": "g",
        "daily_target_minutes": 30,
        "weekdays": frozenset(range(7)),
        "processes": (),
        "created_at": "",
        "updated_at": "",
    }
    fields.update(overrides)
    return Goal(**fields)


# --- Goal 규칙 ---


def test_a_goal_without_a_period_covers_every_day() -> None:
    goal = _goal()
    assert goal.covers(date(1999, 1, 1)) and goal.covers(date(2099, 1, 1))
    assert not goal.ended_before(date(2099, 1, 1))


def test_a_period_includes_both_end_days_and_nothing_else() -> None:
    goal = _goal(start_date=date(2026, 11, 10), end_date=date(2026, 11, 12))
    assert [goal.covers(date(2026, 11, day)) for day in (9, 10, 11, 12, 13)] == [False, True, True, True, False]
    assert goal.ended_before(date(2026, 11, 13)) and not goal.ended_before(date(2026, 11, 12))


def test_a_goal_applies_only_on_its_weekdays_inside_the_period() -> None:
    goal = _goal(weekdays=frozenset({0}), start_date=date(2026, 11, 2), end_date=date(2026, 11, 9))  # 월요일만
    assert goal.applies_on(date(2026, 11, 2)) and goal.applies_on(date(2026, 11, 9))
    assert not goal.applies_on(date(2026, 11, 3))  # 요일이 아니다
    assert not goal.applies_on(date(2026, 11, 16))  # 월요일이지만 기간 밖이다


# --- 입력 검증 ---


def test_no_period_is_the_default_and_both_empty_is_allowed(store) -> None:
    goal = _make(store)
    assert (goal.start_date, goal.end_date) == (None, None)
    assert _make(store, "운동", start_date=None, end_date=None).start_date is None


def test_a_period_is_stored_and_read_back(store) -> None:
    goal = _make(store, start_date="2026-11-10", end_date="2026-12-31")
    assert (goal.start_date, goal.end_date) == (date(2026, 11, 10), date(2026, 12, 31))
    assert store.get(goal.id) == goal


def test_both_dates_or_neither(store) -> None:
    assert _errors(lambda: _make(store, start_date="2026-11-10")) == {"end_date": "incomplete"}
    assert _errors(lambda: _make(store, end_date="2026-11-10")) == {"start_date": "incomplete"}


@pytest.mark.parametrize(
    "text",
    ["2026-11-5", "20261110", "2026-W45-3", "2026/11/10", " 2026-11-10", "2026-02-30", "2026-13-01", "0001-01-01", "2101-01-01", "٢٠٢٦-١١-١٠", ""],
)
def test_dates_must_be_strict_iso_text(store, text) -> None:
    assert "start_date" in _errors(lambda: _make(store, start_date=text, end_date="2026-12-31"))


@pytest.mark.parametrize("value", [20261110, 1.5, True, ["2026-11-10"]])
def test_dates_must_be_strings(store, value) -> None:
    assert _errors(lambda: _make(store, start_date=value, end_date="2026-12-31")) == {"start_date": "type"}


def test_the_end_cannot_precede_the_start_but_a_single_day_is_fine(store) -> None:
    assert _errors(lambda: _make(store, start_date="2026-11-12", end_date="2026-11-11")) == {"end_date": "order"}
    assert _make(store, start_date="2026-11-12", end_date="2026-11-12").end_date == date(2026, 11, 12)


def test_the_past_cannot_be_chosen_but_today_can(store) -> None:
    assert _errors(lambda: _make(store, start_date="2026-11-04", end_date="2026-12-01")) == {"start_date": "past"}
    assert _make(store, start_date="2026-11-05", end_date="2026-11-05").start_date == TODAY


def test_a_period_needs_today_to_be_checked(store) -> None:
    with pytest.raises(ValueError):
        store.create(name="x", daily_target_minutes=10, weekdays=ALL_DAYS, processes=[], start_date="2026-11-10", end_date="2026-11-11")
    with pytest.raises(ValueError):
        store.create(name="x", daily_target_minutes=10, weekdays=ALL_DAYS, processes=[], today=datetime(2026, 11, 5))


def test_keeping_an_already_started_period_is_allowed_when_editing_other_fields(store) -> None:
    goal = _make(store, start_date="2026-11-05", end_date="2026-11-30")
    later = date(2026, 11, 20)  # 시작일이 이미 지난 뒤
    edited = store.update(
        goal.id, name="공부2", daily_target_minutes=90, weekdays=ALL_DAYS, processes=[], start_date="2026-11-05", end_date="2026-11-30", today=later
    )
    assert (edited.start_date, edited.end_date, edited.daily_target_minutes) == (date(2026, 11, 5), date(2026, 11, 30), 90)


def test_changing_the_start_or_end_into_the_past_is_refused_when_editing(store) -> None:
    goal = _make(store, start_date="2026-11-05", end_date="2026-11-30")
    later = date(2026, 11, 20)

    def edit(**period):
        return store.update(goal.id, name="공부", daily_target_minutes=60, weekdays=ALL_DAYS, processes=[], today=later, **period)

    assert _errors(lambda: edit(start_date="2026-11-10", end_date="2026-11-30")) == {"start_date": "past"}  # 시작일을 과거 값으로 바꿨다
    assert _errors(lambda: edit(start_date="2026-11-05", end_date="2026-11-19")) == {"end_date": "past"}
    assert edit(start_date="2026-11-05", end_date="2026-12-31").end_date == date(2026, 12, 31)  # 종료일을 늘리는 것은 된다


def test_a_period_can_be_cleared_when_editing(store) -> None:
    goal = _make(store, start_date="2026-11-10", end_date="2026-11-30")
    cleared = store.update(goal.id, name="공부", daily_target_minutes=60, weekdays=ALL_DAYS, processes=[], today=TODAY)
    assert (cleared.start_date, cleared.end_date) == (None, None)


def test_editing_a_missing_goal_is_not_found_before_validation(store) -> None:
    with pytest.raises(GoalNotFoundError):
        store.update(99, name="x", daily_target_minutes=10, weekdays=ALL_DAYS, processes=[], start_date="bad", end_date="bad", today=TODAY)


def test_the_database_checks_the_date_shape_even_without_validation(tmp_path, store) -> None:
    goal = _make(store)
    raw = sqlite3.connect(tmp_path / "goals.db")
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute("UPDATE goals SET start_date = 'soon' WHERE id = ?", (goal.id,))


# --- 스키마 5 ---


def test_a_version_4_database_gets_the_period_columns_and_keeps_its_goals(tmp_path) -> None:
    path = tmp_path / "goals.db"
    with GoalStore(path, now=_Clock()) as old:
        old.create(name="옛 목표", daily_target_minutes=30, weekdays=ALL_DAYS, processes=[])
    raw = sqlite3.connect(path)
    raw.execute("ALTER TABLE goals DROP COLUMN start_date")
    raw.execute("ALTER TABLE goals DROP COLUMN end_date")
    raw.execute("PRAGMA user_version = 4")
    raw.commit()
    raw.close()
    with GoalStore(path, now=_Clock()) as migrated:
        [goal] = migrated.list_goals()
        assert (goal.name, goal.start_date, goal.end_date) == ("옛 목표", None, None)
        edited = migrated.update(
            goal.id, name="옛 목표", daily_target_minutes=30, weekdays=ALL_DAYS, processes=[], start_date="2026-11-10", end_date="2026-11-20", today=TODAY
        )
        assert edited.start_date == date(2026, 11, 10)
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


# --- 목표량(분모)과 스냅샷 ---


def test_the_target_counts_only_days_inside_the_period(store) -> None:
    goal = _make(store, start_date="2026-11-05", end_date="2026-11-07")
    days = [date(2026, 11, day) for day in range(3, 11)]  # 3~10일
    assert period_target_minutes(store, days)[goal.id] == 3 * 60  # 5·6·7일만


def test_goals_for_day_skips_goals_outside_their_period(store) -> None:
    _make(store, start_date="2026-11-10", end_date="2026-11-12")
    current = store.list_goals()
    assert goals_for_day(store, date(2026, 11, 9), current) == []
    assert len(goals_for_day(store, date(2026, 11, 11), current)) == 1
    assert goals_for_day(store, date(2026, 11, 13), current) == []


def test_snapshot_today_records_only_goals_inside_their_period(store) -> None:
    _make(store, "진행 중", start_date="2026-11-05", end_date="2026-11-30")
    _make(store, "예정", start_date="2026-11-20", end_date="2026-11-30")
    assert [snapshot.name for snapshot in store.snapshot_today(TODAY)] == ["진행 중"]


# --- 알림 ---


def test_alerts_are_not_evaluated_outside_the_goals_period(tmp_path) -> None:
    clock = _Clock()
    clock.now = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)  # 규칙은 4일에 만든다(마감 전)
    with GoalStore(tmp_path / "alerts.db", now=clock) as alert_store:
        goal = alert_store.create(
            name="끝남", daily_target_minutes=30, weekdays=ALL_DAYS, processes=[], start_date="2026-11-05", end_date="2026-11-05", today=date(2026, 11, 4)
        )
        alert_store.create_alert(goal.id, target_process=None, deadline="23:00", min_minutes=10, weekdays=ALL_DAYS, enabled=True)

        def due(day: int):
            now = datetime(2026, 11, day, 23, 30, tzinfo=LOCAL)
            return due_alerts(
                alert_store.list_alerts(), alert_store.list_goals(), now=now, seconds_by_process={}, goal_seconds={}, already_fired=()
            )

        assert due(4) == []  # 아직 시작하지 않았다
        assert len(due(5)) == 1  # 기간 안 — 못 채웠으니 알린다
        assert due(6) == [] and due(20) == []  # 끝난 뒤에는 알리지 않는다


# --- 수행 시간(분자)의 기간 창 ---


def test_the_window_is_the_overlap_of_the_range_and_the_period() -> None:
    goal = _goal(start_date=date(2026, 11, 10), end_date=date(2026, 11, 12))
    start = datetime(2026, 11, 1, tzinfo=LOCAL)
    end = datetime(2026, 11, 30, tzinfo=LOCAL)
    window = period_window(goal, start, end)
    assert window is not None
    assert window[0].astimezone(LOCAL).date() == date(2026, 11, 10)
    assert window[1].astimezone(LOCAL).date() == date(2026, 11, 13)  # 종료일 다음 날 자정(끝 미포함)
    inside = period_window(goal, datetime(2026, 11, 11, tzinfo=LOCAL), datetime(2026, 11, 20, tzinfo=LOCAL))
    assert inside is not None and inside[0].astimezone(LOCAL).date() == date(2026, 11, 11)
    assert period_window(goal, datetime(2026, 11, 13, tzinfo=LOCAL), datetime(2026, 11, 20, tzinfo=LOCAL)) is None
    assert period_window(goal, datetime(2026, 11, 1, tzinfo=LOCAL), datetime(2026, 11, 10, tzinfo=LOCAL)) is None


def test_a_goal_without_a_period_uses_the_whole_range() -> None:
    start, end = datetime(2026, 11, 1, tzinfo=LOCAL), datetime(2026, 11, 30, tzinfo=LOCAL)
    assert period_window(_goal(), start, end) == (start, end)


def test_each_goal_is_computed_from_its_own_table() -> None:
    first = _goal(id=1, processes=("a.exe",))
    second = _goal(id=2, processes=("b.exe",))
    tables = {1: ({"a.exe": 100.0, "b.exe": 999.0}, None), 2: ({"b.exe": 7.0}, None)}
    progress, summary = compute_progress_per_goal([first, second], lambda goal: tables[goal.id])
    assert [item.active_seconds for item in progress] == [100.0, 7.0]  # 첫 목표의 표에 있는 b.exe는 첫 목표와 무관하다
    assert summary.active_seconds == 107.0
    assert summary.top is not None and summary.top.process == "a.exe"
