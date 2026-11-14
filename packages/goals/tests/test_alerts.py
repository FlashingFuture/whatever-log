import sqlite3
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from goals import MAX_ALERTS_PER_GOAL, GoalNotFoundError, GoalStore, GoalValidationError, due_alerts
from goals.store import SCHEMA_VERSION

KST = timezone(timedelta(hours=9))
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)  # KST 12:00, 목요일

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def store(tmp_path, clock):
    with GoalStore(tmp_path / "goals.db", now=clock) as opened:
        yield opened


@pytest.fixture
def goal(store):
    return store.create(
        name="게임",
        daily_target_minutes=30,
        weekdays=ALL_DAYS,
        processes=["Arknights.exe", "Other.exe"],
        known_processes=["Arknights.exe", "Other.exe"],
    )


def _alert(**overrides):
    fields = {"target_process": None, "deadline": "23:00", "min_minutes": 1, "weekdays": ALL_DAYS, "enabled": True}
    fields.update(overrides)
    return fields


def _errors(call):
    with pytest.raises(GoalValidationError) as caught:
        call()
    return {error.field: error.code for error in caught.value.errors}


# --- 입력 검증 ---


def test_an_alert_can_target_the_whole_goal_or_one_linked_process(store, goal):
    whole = store.create_alert(goal.id, **_alert())
    one = store.create_alert(goal.id, **_alert(target_process="arknights.EXE"))
    assert whole.target_process is None
    assert one.target_process == "Arknights.exe"  # 연결한 이름 그대로 저장한다(대소문자 무시로 맞춘다)
    assert [alert.id for alert in store.list_alerts(goal.id)] == [whole.id, one.id]


def test_a_process_that_is_not_linked_to_the_goal_is_rejected(store, goal):
    assert _errors(lambda: store.create_alert(goal.id, **_alert(target_process="chrome.exe"))) == {
        "target_process": "not_linked"
    }


@pytest.mark.parametrize("deadline", ["9:00", "24:00", "23:60", "23:00:00", "", "2300", 2300, None])
def test_the_deadline_must_be_hh_mm(store, goal, deadline):
    assert "deadline" in _errors(lambda: store.create_alert(goal.id, **_alert(deadline=deadline)))


@pytest.mark.parametrize("minutes", [0, 1441, -1, 1.5, "5", True, None])
def test_the_minimum_minutes_must_be_a_plain_int_in_range(store, goal, minutes):
    assert "min_minutes" in _errors(lambda: store.create_alert(goal.id, **_alert(min_minutes=minutes)))


@pytest.mark.parametrize("weekdays", [[], [7], [0, 0], "월", None])
def test_the_weekdays_are_checked_like_a_goals(store, goal, weekdays):
    assert "weekdays" in _errors(lambda: store.create_alert(goal.id, **_alert(weekdays=weekdays)))


@pytest.mark.parametrize("enabled", [1, "true", None])
def test_enabled_must_be_a_boolean(store, goal, enabled):
    assert "enabled" in _errors(lambda: store.create_alert(goal.id, **_alert(enabled=enabled)))


def test_every_wrong_field_is_reported_at_once(store, goal):
    errors = _errors(lambda: store.create_alert(goal.id, **_alert(deadline="x", min_minutes=0, weekdays=[])))
    assert set(errors) == {"deadline", "min_minutes", "weekdays"}


def test_an_alert_for_a_missing_goal_is_not_found(store):
    with pytest.raises(GoalNotFoundError):
        store.create_alert(99, **_alert())


def test_a_goal_can_have_only_so_many_alerts(store, goal):
    for _ in range(MAX_ALERTS_PER_GOAL):
        store.create_alert(goal.id, **_alert())
    assert _errors(lambda: store.create_alert(goal.id, **_alert())) == {"alerts": "too_many"}


def test_deleting_a_goal_deletes_its_alerts_and_schedule(store, goal):
    alert = store.create_alert(goal.id, **_alert())
    store.mark_alert_fired(alert.id, date(2026, 11, 5))
    store.set_report_schedule(goal.id, enabled=True, frequency="daily", weekday=None, day_of_month=None, send_time="09:00")
    store.delete(goal.id)
    assert store.list_alerts() == []
    assert store.report_schedule(goal.id) is None
    assert store.fired_alert_ids(date(2026, 11, 5)) == set()


def test_update_and_delete(store, goal):
    alert = store.create_alert(goal.id, **_alert())
    updated = store.update_alert(alert.id, **_alert(deadline="22:30", min_minutes=10, enabled=False))
    assert (updated.deadline, updated.min_minutes, updated.enabled) == ("22:30", 10, False)
    store.delete_alert(alert.id)
    assert store.get_alert(alert.id) is None
    with pytest.raises(GoalNotFoundError):
        store.delete_alert(alert.id)
    with pytest.raises(GoalNotFoundError):
        store.update_alert(alert.id, **_alert())


def test_the_fired_record_is_once_per_day_and_only_a_condition_change_clears_it(store, goal):
    alert = store.create_alert(goal.id, **_alert())
    day = date(2026, 11, 5)
    assert store.mark_alert_fired(alert.id, day) is True
    assert store.mark_alert_fired(alert.id, day) is False  # 이미 알렸다
    assert store.fired_alert_ids(day) == {alert.id}
    store.update_alert(alert.id, **_alert(enabled=False))  # 켜짐 여부만 바뀌면 기록을 지우지 않는다
    assert store.fired_alert_ids(day) == {alert.id}
    store.update_alert(alert.id, **_alert(deadline="22:00"))  # 조건이 바뀌면 오늘 다시 평가받는다
    assert store.fired_alert_ids(day) == set()
    assert store.mark_alert_fired(999, day) is False  # 없는 규칙


def test_old_fired_records_are_pruned(store, goal):
    alert = store.create_alert(goal.id, **_alert())
    store.mark_alert_fired(alert.id, date(2026, 9, 1))
    store.mark_alert_fired(alert.id, date(2026, 11, 5))
    assert store.fired_alert_ids(date(2026, 9, 1)) == set()


def test_the_database_checks_the_deadline_even_without_validation(tmp_path, store, goal):
    raw = sqlite3.connect(tmp_path / "goals.db")
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO goal_alerts (goal_id, deadline, min_minutes, weekdays, enabled, created_at, updated_at) "
            "VALUES (?, 'bad', 1, 127, 1, 'x', 'x')",
            (goal.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):  # 이름과 키는 함께 있거나 함께 없어야 한다
        raw.execute(
            "INSERT INTO goal_alerts (goal_id, target_name, deadline, min_minutes, weekdays, enabled, created_at, updated_at) "
            "VALUES (?, 'a.exe', '23:00', 1, 127, 1, 'x', 'x')",
            (goal.id,),
        )


def test_a_version_3_database_gets_the_new_tables(tmp_path):
    path = tmp_path / "goals.db"
    with GoalStore(path):
        pass
    raw = sqlite3.connect(path)
    for table in ("goal_alert_log", "goal_alerts", "goal_report_schedules"):
        raw.execute(f"DROP TABLE {table}")
    raw.execute("PRAGMA user_version = 3")
    raw.commit()
    raw.close()
    with GoalStore(path) as store:
        assert store.list_alerts() == []
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)


# --- 보고서 일정 ---


def _schedule(**overrides):
    fields = {"enabled": True, "frequency": "daily", "weekday": None, "day_of_month": None, "send_time": "09:00"}
    fields.update(overrides)
    return fields


def test_a_schedule_is_created_replaced_and_deleted(store, goal):
    assert store.report_schedule(goal.id) is None
    first = store.set_report_schedule(goal.id, **_schedule(frequency="weekly", weekday=0))
    assert (first.frequency, first.weekday, first.day_of_month) == ("weekly", 0, None)
    second = store.set_report_schedule(goal.id, **_schedule(frequency="monthly", day_of_month=15, send_time="21:30"))
    assert (second.frequency, second.weekday, second.day_of_month, second.send_time) == ("monthly", None, 15, "21:30")
    assert second.created_at == first.created_at
    store.delete_report_schedule(goal.id)
    assert store.report_schedule(goal.id) is None
    with pytest.raises(GoalNotFoundError):
        store.delete_report_schedule(goal.id)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"frequency": "yearly"}, "frequency"),
        ({"frequency": "weekly"}, "weekday"),
        ({"frequency": "weekly", "weekday": 7}, "weekday"),
        ({"frequency": "weekly", "weekday": 1, "day_of_month": 3}, "day_of_month"),
        ({"frequency": "monthly"}, "day_of_month"),
        ({"frequency": "monthly", "day_of_month": 29}, "day_of_month"),
        ({"frequency": "monthly", "day_of_month": 0}, "day_of_month"),
        ({"frequency": "monthly", "day_of_month": 3, "weekday": 1}, "weekday"),
        ({"frequency": "daily", "weekday": 1}, "weekday"),
        ({"frequency": "daily", "day_of_month": 1}, "day_of_month"),
        ({"send_time": "9:00"}, "send_time"),
        ({"enabled": "yes"}, "enabled"),
    ],
)
def test_invalid_schedules_are_rejected(store, goal, overrides, field):
    assert field in _errors(lambda: store.set_report_schedule(goal.id, **_schedule(**overrides)))


def test_a_schedule_for_a_missing_goal_is_not_found(store):
    with pytest.raises(GoalNotFoundError):
        store.set_report_schedule(99, **_schedule())


# --- 지금 알려야 할 알림 판단 ---


def _due(store, now, *, seconds_by_process=None, goal_seconds=None, fired=()):
    return due_alerts(
        store.list_alerts(),
        store.list_goals(),
        now=now,
        seconds_by_process=seconds_by_process or {},
        goal_seconds=goal_seconds or {},
        already_fired=fired,
    )


def _evening(hour, minute=0):
    return datetime(2026, 11, 5, hour, minute, tzinfo=KST)  # 목요일(알림은 KST 12:00에 만든다)


def test_nothing_is_due_before_the_deadline_and_the_alert_is_due_after_it(store, goal):
    store.create_alert(goal.id, **_alert(deadline="23:00"))
    assert _due(store, _evening(22, 59)) == []
    [due] = _due(store, _evening(23, 0))
    assert (due.goal_name, due.active_minutes) == ("게임", 0)


def test_an_alert_is_not_due_when_the_target_was_done(store, goal):
    store.create_alert(goal.id, **_alert(min_minutes=10))
    assert _due(store, _evening(23, 30), goal_seconds={goal.id: 599}) != []
    assert _due(store, _evening(23, 30), goal_seconds={goal.id: 600}) == []


def test_a_process_alert_counts_only_that_process_case_insensitively(store, goal):
    store.create_alert(goal.id, **_alert(target_process="Arknights.exe", min_minutes=5))
    done = {"arknights.EXE": 200.0, "ARKNIGHTS.exe": 100.0}  # 대소문자만 다른 두 기록은 합친다(300초 = 5분)
    assert _due(store, _evening(23, 30), seconds_by_process=done) == []
    other = {"Other.exe": 99999.0}  # 같은 목표의 다른 프로세스를 오래 써도 이 규칙의 대상이 아니다
    assert [d.active_minutes for d in _due(store, _evening(23, 30), seconds_by_process=other)] == [0]


def test_a_fired_alert_is_not_due_again(store, goal):
    alert = store.create_alert(goal.id, **_alert())
    assert _due(store, _evening(23, 30), fired={alert.id}) == []


def test_a_disabled_alert_and_a_wrong_weekday_are_not_due(store, goal):
    store.create_alert(goal.id, **_alert(enabled=False))
    store.create_alert(goal.id, **_alert(weekdays=[0]))  # 월요일만 — 2026-11-05는 목요일
    assert _due(store, _evening(23, 30)) == []


def test_an_alert_created_after_todays_deadline_waits_until_tomorrow(store, goal, clock):
    clock.now = datetime(2026, 11, 5, 14, 30, tzinfo=UTC)  # KST 23:30
    store.create_alert(goal.id, **_alert(deadline="23:00"))
    assert _due(store, _evening(23, 45)) == []
    tomorrow = datetime(2026, 11, 6, 23, 5, tzinfo=KST)
    assert len(_due(store, tomorrow)) == 1


def test_an_alert_whose_process_is_no_longer_linked_is_skipped(store, goal):
    store.create_alert(goal.id, **_alert(target_process="Other.exe"))
    store.update(
        goal.id,
        name="게임",
        daily_target_minutes=30,
        weekdays=ALL_DAYS,
        processes=["Arknights.exe"],
        known_processes=["Arknights.exe", "Other.exe"],
    )
    assert _due(store, _evening(23, 30)) == []


def test_now_must_carry_a_timezone(store, goal):
    store.create_alert(goal.id, **_alert())
    with pytest.raises(ValueError):
        _due(store, datetime(2026, 11, 5, 23, 30))
