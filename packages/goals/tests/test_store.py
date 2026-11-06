import sqlite3
import unicodedata
from datetime import UTC, date, datetime, time, timedelta

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
def clock():
    return _Clock()


@pytest.fixture
def store(tmp_path, clock):
    with GoalStore(tmp_path / "goals.db", now=clock) as opened:
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
    store.create(**_fields(name="공부", processes=["b.exe"]))

    assert _error_codes(lambda: store.create(**_fields(name="sTUDY", processes=["c.exe"]))) == {
        "name": "duplicate"
    }
    # 같은 글자의 다른 유니코드 표현(NFD)도 같은 이름이다.
    decomposed = unicodedata.normalize("NFD", "공부")
    assert decomposed != "공부"
    assert _error_codes(lambda: store.create(**_fields(name=decomposed, processes=["d.exe"]))) == {
        "name": "duplicate"
    }


def test_format_errors_and_conflicts_are_reported_together(store) -> None:
    """이름이 이미 있고 시간도 틀렸으면, 한 번에 둘 다 알려 사용자가 한 번에 고칠 수 있다."""
    store.create(**_fields(name="공부", processes=["Code.exe"]))

    codes = _error_codes(
        lambda: store.create(
            name="공부", daily_target_minutes=0, weekdays=[0], processes=["Code.exe", "nope"]
        )
    )

    assert codes == {
        "daily_target_minutes": "range",
        "processes[1]": "not_exe",
        "name": "duplicate",
        "processes": "already_linked",  # 형식이 맞는 Code.exe는 충돌까지 같이 확인한다
    }


def test_a_bad_field_does_not_hide_conflicts_in_the_other_fields_but_is_not_trusted(store) -> None:
    store.create(**_fields(name="공부", processes=["Code.exe"]))

    # 이름 칸이 형식 오류(공백)이면 이름 충돌은 확인하지 않는다(믿을 수 없는 값이라서).
    codes = _error_codes(
        lambda: store.create(**_fields(name=" 공부", processes=["zoom.exe"]))
    )

    assert codes == {"name": "whitespace_edges"}


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
            "INSERT INTO goal_targets (goal_id, kind, name, name_key) VALUES (?, 'window', 'a.com', 'a.com')",
            (other.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):  # 범위 밖 값
        raw.execute(
            "INSERT INTO goals (name, name_key, daily_target_minutes, weekdays, created_at, updated_at) "
            "VALUES ('x', 'x', 0, 1, 't', 't')"
        )
    raw.close()


def test_numeric_columns_reject_non_integer_values_at_the_database_level(tmp_path) -> None:
    """SQLite는 INTEGER 열에 1.5를 REAL로 그대로 보관한다 — 범위 CHECK만으로는 통과하므로 타입도 확인한다."""
    path = tmp_path / "goals.db"
    with GoalStore(path):
        pass
    raw = sqlite3.connect(path)
    bad_goals = [
        "INSERT INTO goals (name, name_key, daily_target_minutes, weekdays, created_at, updated_at) "
        "VALUES ('x', 'x', 1.5, 1, 't', 't')",
        "INSERT INTO goals (name, name_key, daily_target_minutes, weekdays, created_at, updated_at) "
        "VALUES ('y', 'y', 60, 1.5, 't', 't')",
        "INSERT INTO goal_snapshots (day, goal_id, name, daily_target_minutes, recorded_at) "
        "VALUES ('2026-11-05', 1, 'z', 1.5, 't')",
    ]
    for statement in bad_goals:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(statement)
    raw.close()


class _CommitFails:
    """COMMIT만 실패하는 연결 — 디스크 가득 참 같은 상황을 흉내 낸다."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql, *args):
        if sql == "COMMIT":
            raise sqlite3.OperationalError("disk full")
        return self._conn.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_a_failed_commit_leaves_no_open_transaction(store) -> None:
    real = store._conn
    store._conn = _CommitFails(real)

    with pytest.raises(sqlite3.OperationalError):
        store.create(**_fields())

    assert not real.in_transaction  # 열린 채 남으면 다음 쓰기가 "이미 트랜잭션 안"으로 깨진다
    store._conn = real
    assert store.list_goals() == []
    assert store.create(**_fields())  # 이후의 쓰기는 정상이다


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


def _snap(store, clock, day: date):
    """시계를 그날로 맞춘 뒤 스냅샷을 기록한다(오늘 날짜는 시계와 하루 안쪽이어야 한다)."""
    clock.now = datetime.combine(day, time(12, 0), tzinfo=UTC)
    return store.snapshot_today(day)


def test_snapshot_records_only_goals_scheduled_for_that_weekday(store, clock) -> None:
    store.create(**_fields(name="평일", weekdays=[0, 1, 2, 3, 4], processes=["Code.exe"]))
    store.create(**_fields(name="주말", weekdays=[5, 6], processes=["Zoom.exe"]))

    monday = _snap(store, clock, MONDAY)
    saturday = _snap(store, clock, SATURDAY)

    assert [snap.name for snap in monday] == ["평일"]
    assert monday[0].processes == ("Code.exe",)
    assert [snap.name for snap in saturday] == ["주말"]
    assert store.snapshots(MONDAY) == monday  # 다른 날의 기록은 따로 남는다


def test_todays_snapshot_follows_edits_until_the_day_passes(store, clock) -> None:
    goal = store.create(**_fields(weekdays=[0], processes=["Code.exe"]))
    _snap(store, clock, MONDAY)

    store.update(goal.id, **_fields(daily_target_minutes=30, weekdays=[0], processes=["Code.exe"]))
    refreshed = _snap(store, clock, MONDAY)

    assert [snap.daily_target_minutes for snap in refreshed] == [30]


def test_a_goal_removed_or_moved_off_today_leaves_todays_snapshot(store, clock) -> None:
    """오래된 행을 지우지 않고 값만 덮어쓰는 구현이면 사라진 목표가 오늘 스냅샷에 남는다."""
    removed = store.create(**_fields(name="삭제", weekdays=[0], processes=["Zoom.exe"]))
    moved = store.create(**_fields(name="이동", weekdays=[0], processes=["Code.exe"]))
    _snap(store, clock, MONDAY)

    store.delete(removed.id)
    store.update(moved.id, **_fields(name="이동", weekdays=[5], processes=["Code.exe"]))

    assert _snap(store, clock, MONDAY) == []


def test_a_past_day_is_frozen_when_goals_change_later(store, clock) -> None:
    goal = store.create(**_fields(daily_target_minutes=120, weekdays=[0], processes=["Code.exe"]))
    _snap(store, clock, MONDAY)

    # 다음 날부터 목표를 바꾸고 삭제한다 — 월요일의 기록은 그대로여야 한다.
    store.update(goal.id, **_fields(name="바뀜", daily_target_minutes=10, weekdays=[0], processes=["x.exe"]))
    store.delete(goal.id)
    _snap(store, clock, date(2026, 11, 3))

    [frozen] = store.snapshots(MONDAY)
    assert (frozen.name, frozen.daily_target_minutes, frozen.processes) == ("공부", 120, ("Code.exe",))
    assert frozen.goal_id == goal.id  # 목표가 삭제돼도 기록은 남는다


def test_an_earlier_day_than_the_latest_snapshot_cannot_overwrite_a_frozen_day(store, clock) -> None:
    """호출부가 지난 날짜를 잘못 넘겨도 확정된 기록이 덮어써지지 않는다."""
    store.create(**_fields(name="평일", weekdays=[0, 5], processes=["Code.exe"]))
    monday = _snap(store, clock, MONDAY)
    _snap(store, clock, SATURDAY)

    clock.now = datetime.combine(MONDAY, time(12, 0), tzinfo=UTC)  # 시계는 월요일이지만 이미 토요일까지 기록됨
    with pytest.raises(ValueError, match="더 이른 날"):
        store.snapshot_today(MONDAY)

    assert store.snapshots(MONDAY) == monday


def test_a_day_far_from_the_clock_is_rejected(store, clock) -> None:
    store.create(**_fields(weekdays=[0, 1, 2, 3, 4, 5, 6]))
    clock.now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

    for wrong in (date(2020, 1, 1), date(2099, 1, 1), date(2026, 11, 8), date(2026, 11, 3)):
        with pytest.raises(ValueError, match="하루를 넘게"):
            store.snapshot_today(wrong)
    # 시간대에 따라 "오늘"은 UTC 날짜의 앞뒤 하루까지 가능하다.
    for ok in (date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)):
        clock.now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        store.snapshot_today(ok)
        assert store.snapshots(ok)


def test_snapshot_requires_a_plain_date(store) -> None:
    with pytest.raises(ValueError):
        store.snapshot_today(datetime(2026, 11, 2, 9, 0))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        store.snapshot_today("2026-11-02")  # type: ignore[arg-type]


def test_snapshots_of_an_unrecorded_day_are_empty(store) -> None:
    assert store.snapshots(MONDAY + timedelta(days=30)) == []
