import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from goals import (
    MAX_GOALS,
    GoalNotFoundError,
    GoalStore,
    GoalValidationError,
    SchemaVersionError,
)
from goals.store import SCHEMA_VERSION


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def store(tmp_path):
    with GoalStore(tmp_path / "goals.db", now=_Clock()) as opened:
        yield opened


def _fields(**overrides):
    fields = {
        "name": "공부",
        "daily_target_minutes": 120,
        "weekdays": [0, 1, 2, 3, 4],
        "processes": ["Code.exe", "chrome.exe"],
    }
    fields.update(overrides)
    return fields


def _error_codes(callable_) -> dict[str, str]:
    with pytest.raises(GoalValidationError) as exc_info:
        callable_()
    return {error.field: error.code for error in exc_info.value.errors}


def test_create_and_read_back(store) -> None:
    goal = store.create(**_fields())

    assert (goal.name, goal.daily_target_minutes) == ("공부", 120)
    assert goal.weekdays == frozenset({0, 1, 2, 3, 4})
    assert goal.processes == ("chrome.exe", "Code.exe")  # 대소문자를 구분하지 않는 순서
    assert goal.created_at == goal.updated_at == "2026-11-05T03:00:00+00:00"
    assert store.get(goal.id) == goal
    assert store.list_goals() == [goal]
    assert store.get(999) is None


def test_goals_persist_across_connections(tmp_path) -> None:
    path = tmp_path / "goals.db"
    with GoalStore(path) as first:
        created = first.create(**_fields())

    with GoalStore(path) as second:
        assert second.list_goals() == [created]


def test_invalid_input_is_never_stored(store) -> None:
    codes = _error_codes(lambda: store.create(**_fields(name="", processes=["x"])))

    assert codes == {"name": "length", "processes[0]": "not_exe"}
    assert store.list_goals() == []


def test_duplicate_goal_names_are_rejected_case_and_form_insensitively(store) -> None:
    store.create(**_fields(name="Study", processes=["a.exe"]))

    assert _error_codes(lambda: store.create(**_fields(name="sTUDY", processes=["b.exe"]))) == {
        "name": "duplicate"
    }


def test_a_process_can_belong_to_only_one_goal(store) -> None:
    store.create(**_fields(name="공부", processes=["Code.exe"]))

    with pytest.raises(GoalValidationError) as exc_info:
        store.create(**_fields(name="운동", processes=["code.exe", "Zoom.exe"]))  # 대소문자만 다르다

    [error] = exc_info.value.errors
    assert (error.field, error.code) == ("processes", "already_linked")
    assert "공부" in error.message and "code.exe" in error.message
    assert len(store.list_goals()) == 1


def test_the_one_goal_per_process_rule_also_holds_at_the_database_level(tmp_path) -> None:
    """검증을 거치지 않는 경로가 생겨도 스키마가 마지막으로 막는다."""
    path = tmp_path / "goals.db"
    with GoalStore(path) as store:
        store.create(**_fields(name="A", processes=["Code.exe"]))
        other = store.create(**_fields(name="B", processes=["zoom.exe"]))

    raw = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO goal_targets (goal_id, kind, name, name_key) VALUES (?, 'process', 'CODE.EXE', 'code.exe')",
            (other.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):  # 모르는 종류는 CHECK가 막는다
        raw.execute(
            "INSERT INTO goal_targets (goal_id, kind, name, name_key) VALUES (?, 'site', 'a.com', 'a.com')",
            (other.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):  # 범위 밖 값
        raw.execute(
            "INSERT INTO goals (name, name_key, daily_target_minutes, weekdays, created_at, updated_at) "
            "VALUES ('x', 'x', 0, 1, 't', 't')"
        )
    raw.close()


def test_the_number_of_goals_is_limited(store) -> None:
    for index in range(MAX_GOALS):
        store.create(**_fields(name=f"목표{index}", processes=[f"app{index}.exe"]))

    assert _error_codes(lambda: store.create(**_fields(name="하나 더", processes=["extra.exe"]))) == {
        "goals": "too_many"
    }


def test_update_replaces_the_whole_goal(store) -> None:
    goal = store.create(**_fields())

    updated = store.update(
        goal.id, name="코딩", daily_target_minutes=90, weekdays=[5, 6], processes=["Code.exe"]
    )

    assert (updated.name, updated.daily_target_minutes) == ("코딩", 90)
    assert updated.weekdays == frozenset({5, 6})
    assert updated.processes == ("Code.exe",)
    assert updated.created_at == goal.created_at


def test_update_keeps_its_own_name_and_processes_without_conflict(store) -> None:
    goal = store.create(**_fields())

    again = store.update(goal.id, **_fields(daily_target_minutes=60))  # 이름·프로세스는 그대로

    assert again.daily_target_minutes == 60


def test_update_cannot_take_another_goals_name_or_processes(store) -> None:
    store.create(**_fields(name="공부", processes=["Code.exe"]))
    other = store.create(**_fields(name="운동", processes=["Zoom.exe"]))

    assert _error_codes(lambda: store.update(other.id, **_fields(name="공부", processes=["Zoom.exe"]))) == {
        "name": "duplicate"
    }
    assert _error_codes(lambda: store.update(other.id, **_fields(name="운동", processes=["Code.exe"]))) == {
        "processes": "already_linked"
    }
    assert store.get(other.id).processes == ("Zoom.exe",)  # 실패한 변경은 반영되지 않는다


def test_a_freed_process_can_be_linked_to_another_goal(store) -> None:
    first = store.create(**_fields(name="공부", processes=["Code.exe"]))
    store.update(first.id, **_fields(name="공부", processes=["chrome.exe"]))

    second = store.create(**_fields(name="코딩", processes=["Code.exe"]))

    assert second.processes == ("Code.exe",)


def test_update_and_delete_report_unknown_ids(store) -> None:
    with pytest.raises(GoalNotFoundError):
        store.update(42, **_fields())
    with pytest.raises(GoalNotFoundError):
        store.delete(42)


def test_delete_removes_the_goal_and_frees_its_processes(store) -> None:
    goal = store.create(**_fields(processes=["Code.exe"]))

    store.delete(goal.id)

    assert store.list_goals() == []
    assert store.create(**_fields(name="다시", processes=["Code.exe"]))  # 연결이 풀렸다


def test_a_failed_write_changes_nothing(store, monkeypatch) -> None:
    goal = store.create(**_fields())
    monkeypatch.setattr(store, "_insert_targets", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        store.update(goal.id, **_fields(name="바뀐 이름", processes=["x.exe"]))

    assert store.get(goal.id) == goal  # 이름도 연결도 원래대로(트랜잭션이 되돌려졌다)


def test_a_database_from_a_newer_version_is_refused(tmp_path) -> None:
    path = tmp_path / "goals.db"
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    raw.close()

    with pytest.raises(SchemaVersionError):
        GoalStore(path)


# --- 하루 스냅샷 ---

MONDAY = date(2026, 11, 2)
SATURDAY = date(2026, 11, 7)


def test_snapshot_records_only_goals_scheduled_for_that_weekday(store) -> None:
    store.create(**_fields(name="평일", weekdays=[0, 1, 2, 3, 4], processes=["Code.exe"]))
    store.create(**_fields(name="주말", weekdays=[5, 6], processes=["Zoom.exe"]))

    monday = store.snapshot_today(MONDAY)
    saturday = store.snapshot_today(SATURDAY)

    assert [snap.name for snap in monday] == ["평일"]
    assert monday[0].processes == ("Code.exe",)
    assert [snap.name for snap in saturday] == ["주말"]
    assert store.snapshots(MONDAY) == monday  # 다른 날의 기록은 따로 남는다


def test_todays_snapshot_follows_edits_until_the_day_passes(store) -> None:
    goal = store.create(**_fields(weekdays=[0], processes=["Code.exe"]))
    store.snapshot_today(MONDAY)

    store.update(goal.id, **_fields(daily_target_minutes=30, weekdays=[0], processes=["Code.exe"]))
    refreshed = store.snapshot_today(MONDAY)

    assert [snap.daily_target_minutes for snap in refreshed] == [30]


def test_a_past_day_is_frozen_when_goals_change_later(store) -> None:
    goal = store.create(**_fields(daily_target_minutes=120, weekdays=[0], processes=["Code.exe"]))
    store.snapshot_today(MONDAY)

    # 다음 날부터 목표를 바꾸고 삭제한다 — 월요일의 기록은 그대로여야 한다.
    store.update(goal.id, **_fields(name="바뀜", daily_target_minutes=10, weekdays=[0], processes=["x.exe"]))
    store.delete(goal.id)
    store.snapshot_today(date(2026, 11, 3))

    [frozen] = store.snapshots(MONDAY)
    assert (frozen.name, frozen.daily_target_minutes, frozen.processes) == ("공부", 120, ("Code.exe",))
    assert frozen.goal_id == goal.id  # 목표가 삭제돼도 기록은 남는다


def test_snapshot_requires_a_plain_date(store) -> None:
    with pytest.raises(ValueError):
        store.snapshot_today(datetime(2026, 11, 2, 9, 0))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        store.snapshot_today("2026-11-02")  # type: ignore[arg-type]


def test_snapshots_of_an_unrecorded_day_are_empty(store) -> None:
    assert store.snapshots(MONDAY + timedelta(days=30)) == []
