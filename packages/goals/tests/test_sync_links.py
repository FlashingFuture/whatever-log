import sqlite3
from datetime import UTC, datetime

import pytest

from goals import (
    META_SYNC_ENABLED,
    GoalNotFoundError,
    GoalStore,
    GoalValidationError,
    SyncLink,
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
        "processes": [],
    }
    fields.update(overrides)
    return fields


def _link(store, goal_id) -> SyncLink:
    return next(link for link in store.sync_links() if link.goal_id == goal_id)


def test_a_new_goal_is_undecided_and_not_linked(store) -> None:
    goal = store.create(**_fields())

    assert _link(store, goal.id) == SyncLink(goal.id, "ask", None, None, False)


def test_goals_created_after_sync_is_enabled_are_marked_for_sync(store) -> None:
    store.set_meta(META_SYNC_ENABLED, "1")

    goal = store.create(**_fields())

    assert _link(store, goal.id).state == "sync" and _link(store, goal.id).remote_id is None


_V2_SCHEMA = """
CREATE TABLE goals (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
    daily_target_minutes INTEGER NOT NULL, weekdays INTEGER NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE goal_targets (
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('process', 'site')), name TEXT NOT NULL, name_key TEXT NOT NULL,
    PRIMARY KEY (goal_id, kind, name_key), UNIQUE (kind, name_key));
CREATE TABLE goal_snapshots (
    day TEXT NOT NULL, goal_id INTEGER NOT NULL, name TEXT NOT NULL,
    daily_target_minutes INTEGER NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY (day, goal_id));
CREATE TABLE goal_snapshot_targets (
    day TEXT NOT NULL, goal_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('process', 'site')),
    name TEXT NOT NULL, PRIMARY KEY (day, goal_id, kind, name),
    FOREIGN KEY (day, goal_id) REFERENCES goal_snapshots(day, goal_id) ON DELETE CASCADE);
INSERT INTO goals VALUES (1, '공부', '공부', 120, 31, 't', 't');
INSERT INTO goal_targets VALUES (1, 'process', 'Code.exe', 'code.exe');
PRAGMA user_version = 2;
"""


def test_a_version_2_database_is_migrated_and_existing_goals_are_undecided(tmp_path) -> None:
    path = tmp_path / "goals.db"
    raw = sqlite3.connect(path, isolation_level=None)
    raw.executescript(_V2_SCHEMA)
    raw.close()

    with GoalStore(path) as store:
        (goal,) = store.list_goals()
        assert goal.processes == ("Code.exe",)  # 프로세스 연결은 그대로
        assert store.sync_links() == [SyncLink(1, "ask", None, None, False)]
        store.link_remote(1, "r-1", 3)
        assert _link(store, 1).remote_id == "r-1"
    (version,) = sqlite3.connect(path).execute("PRAGMA user_version").fetchone()
    assert version == SCHEMA_VERSION == 4


def test_choosing_to_sync_or_keep_local_applies_only_to_unlinked_goals(store) -> None:
    goal = store.create(**_fields())

    store.set_sync_state(goal.id, "local_only")
    assert _link(store, goal.id).state == "local_only"
    store.set_sync_state(goal.id, "sync")
    assert _link(store, goal.id).state == "sync"

    store.link_remote(goal.id, "r-1", 1)
    store.set_sync_state(goal.id, "local_only")  # 이미 연결된 목표는 이 경로로 바뀌지 않는다
    assert _link(store, goal.id).state == "sync"


def test_invalid_states_and_unknown_goals_are_rejected(store) -> None:
    goal = store.create(**_fields())

    with pytest.raises(ValueError):
        store.set_sync_state(goal.id, "bogus")
    with pytest.raises(GoalNotFoundError):
        store.set_sync_state(999, "sync")
    with pytest.raises(GoalNotFoundError):
        store.link_remote(999, "r", 1)


def test_the_database_itself_rejects_unknown_states_and_duplicate_remote_ids(store) -> None:
    first = store.create(**_fields(name="A"))
    second = store.create(**_fields(name="B"))
    store.link_remote(first.id, "r-1", 1)

    with pytest.raises(sqlite3.IntegrityError):
        store.link_remote(second.id, "r-1", 1)  # 같은 서버 목표를 두 목표가 가질 수 없다
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE goals SET sync_state = 'bogus' WHERE id = ?", (first.id,))


@pytest.mark.parametrize(
    "change",
    [{"name": "공부2"}, {"daily_target_minutes": 90}, {"weekdays": [0, 1]}],
)
def test_each_server_known_field_marks_a_linked_goal_dirty(store, change) -> None:
    goal = store.create(**_fields(processes=["Code.exe"]))
    store.link_remote(goal.id, "r-1", 1)

    store.update(goal.id, **_fields(processes=["Code.exe"], **change))

    assert _link(store, goal.id).dirty is True


def test_changing_only_the_process_links_does_not_mark_dirty(store) -> None:
    goal = store.create(**_fields())
    store.link_remote(goal.id, "r-1", 1)

    store.update(goal.id, **_fields(processes=["Code.exe"]))

    assert _link(store, goal.id).dirty is False


def test_an_unlinked_goal_never_becomes_dirty(store) -> None:
    goal = store.create(**_fields())

    store.update(goal.id, **_fields(name="바뀜"))

    assert _link(store, goal.id).dirty is False


def test_mark_pushed_clears_dirty_and_records_the_revision(store) -> None:
    goal = store.create(**_fields())
    store.link_remote(goal.id, "r-1", 1)
    store.update(goal.id, **_fields(name="바뀜"))

    store.mark_pushed(goal.id, 2)

    assert _link(store, goal.id) == SyncLink(goal.id, "sync", "r-1", 2, False)


def test_deleting_a_linked_goal_keeps_its_server_id_until_the_server_is_told(store) -> None:
    linked = store.create(**_fields(name="A"))
    local = store.create(**_fields(name="B"))
    store.link_remote(linked.id, "r-1", 1)

    store.delete(linked.id)
    store.delete(local.id)

    assert store.pending_deletions() == ["r-1"]  # 연결 안 된 목표는 서버가 모른다
    store.clear_deletion("r-1")
    assert store.pending_deletions() == []


def test_unlink_keeps_the_goal_and_its_process_links_but_drops_the_server_id(store) -> None:
    goal = store.create(**_fields(processes=["Code.exe"]))
    store.link_remote(goal.id, "r-1", 4)

    store.unlink(goal.id)

    assert _link(store, goal.id) == SyncLink(goal.id, "local_only", None, None, False)
    assert store.get(goal.id).processes == ("Code.exe",)


def test_apply_remote_changes_only_the_shared_fields(store) -> None:
    goal = store.create(**_fields(processes=["Code.exe"]))
    store.link_remote(goal.id, "r-1", 1)
    store.update(goal.id, **_fields(name="로컬 수정", processes=["Code.exe"]))

    store.apply_remote(goal.id, name="서버 이름", daily_target_minutes=45, weekdays=[5, 6], revision=7)

    updated = store.get(goal.id)
    assert (updated.name, updated.daily_target_minutes, updated.weekdays) == ("서버 이름", 45, frozenset({5, 6}))
    assert updated.processes == ("Code.exe",)
    assert _link(store, goal.id) == SyncLink(goal.id, "sync", "r-1", 7, False)


def test_apply_remote_refuses_a_name_another_local_goal_already_has(store) -> None:
    store.create(**_fields(name="운동"))
    goal = store.create(**_fields(name="공부"))

    with pytest.raises(GoalValidationError):
        store.apply_remote(goal.id, name="운동", daily_target_minutes=30, weekdays=[0], revision=2)

    assert store.get(goal.id).name == "공부"


def test_create_from_remote_makes_a_linked_goal_without_process_links(store) -> None:
    goal = store.create_from_remote(remote_id="r-9", name="독서", daily_target_minutes=30, weekdays=[1, 3], revision=2)

    assert (goal.name, goal.processes, goal.sites, goal.weekdays) == ("독서", (), (), frozenset({1, 3}))
    assert _link(store, goal.id) == SyncLink(goal.id, "sync", "r-9", 2, False)


def test_create_from_remote_respects_unique_names_and_the_goal_limit(store) -> None:
    store.create(**_fields(name="공부"))
    with pytest.raises(GoalValidationError):
        store.create_from_remote(remote_id="r-1", name="공부", daily_target_minutes=30, weekdays=[0], revision=1)

    for index in range(19):
        store.create(**_fields(name=f"목표{index}"))
    with pytest.raises(GoalValidationError):
        store.create_from_remote(remote_id="r-2", name="새 목표", daily_target_minutes=30, weekdays=[0], revision=1)


def test_reset_sync_forgets_every_server_link_but_keeps_goals_and_process_links(store) -> None:
    goal = store.create(**_fields(processes=["Code.exe"]))
    gone = store.create(**_fields(name="B"))
    store.link_remote(goal.id, "r-1", 3)
    store.link_remote(gone.id, "r-2", 1)
    store.delete(gone.id)
    store.set_meta(META_SYNC_ENABLED, "1")
    store.set_meta("account_email", "a@example.com")

    store.reset_sync()

    assert _link(store, goal.id) == SyncLink(goal.id, "ask", None, None, False)
    assert store.get(goal.id).processes == ("Code.exe",)
    assert store.pending_deletions() == []
    assert store.get_meta(META_SYNC_ENABLED) is None and store.get_meta("account_email") is None


def test_meta_values_can_be_replaced(store) -> None:
    store.set_meta("k", "1")
    store.set_meta("k", "2")

    assert store.get_meta("k") == "2" and store.get_meta("missing") is None


@pytest.mark.parametrize(
    ("minutes", "weekdays", "field"),
    [
        (0, [0], "daily_target_minutes"),
        (1441, [0], "daily_target_minutes"),
        (True, [0], "daily_target_minutes"),
        ("60", [0], "daily_target_minutes"),
        (60, [], "weekdays"),
        (60, [7], "weekdays"),
        (60, [-1], "weekdays"),
        (60, "0", "weekdays"),
    ],
)
def test_a_server_value_that_breaks_the_local_rules_is_reported_on_its_own_field(store, minutes, weekdays, field) -> None:
    goal = store.create(**_fields())

    with pytest.raises(GoalValidationError) as applied:
        store.apply_remote(goal.id, name="서버 이름", daily_target_minutes=minutes, weekdays=weekdays, revision=3)
    with pytest.raises(GoalValidationError) as created:
        store.create_from_remote(remote_id="r-1", name="독서", daily_target_minutes=minutes, weekdays=weekdays, revision=1)

    for raised in (applied, created):
        assert [error.field for error in raised.value.errors] == [field]  # 이름 중복으로 둔갑하지 않는다
    assert store.get(goal.id).name == "공부" and len(store.list_goals()) == 1  # 아무것도 저장되지 않았다


def test_both_bad_fields_are_reported_together(store) -> None:
    goal = store.create(**_fields())

    with pytest.raises(GoalValidationError) as raised:
        store.apply_remote(goal.id, name="x", daily_target_minutes=0, weekdays=[], revision=1)

    assert sorted(error.field for error in raised.value.errors) == ["daily_target_minutes", "weekdays"]


def test_linking_a_server_goal_that_another_goal_already_has_is_not_called_a_duplicate_name(store) -> None:
    first = store.create(**_fields(name="A"))
    store.link_remote(first.id, "r-1", 1)

    with pytest.raises(GoalValidationError) as raised:
        store.create_from_remote(remote_id="r-1", name="B", daily_target_minutes=30, weekdays=[0], revision=1)

    assert [error.field for error in raised.value.errors] == ["remote_id"]


def test_a_real_name_clash_is_still_reported_as_a_duplicate_name(store) -> None:
    store.create(**_fields(name="공부"))

    with pytest.raises(GoalValidationError) as raised:
        store.create_from_remote(remote_id="r-9", name="공부", daily_target_minutes=30, weekdays=[0], revision=1)

    assert [error.field for error in raised.value.errors] == ["name"]


# --- 동기화 세대: 계정 정리 뒤 낡은 주기의 쓰기 거절 ---


def test_every_account_reset_raises_the_generation_and_keeps_the_device_id(store) -> None:
    from goals import META_DEVICE_ID

    store.set_meta(META_DEVICE_ID, "dev-1")
    first = store.generation()

    store.reset_sync()
    second = store.generation()
    store.reset_sync()

    assert (second, store.generation()) == (first + 1, first + 2)
    assert store.get_meta(META_DEVICE_ID) == "dev-1"  # 계정이 바뀌어도 같은 기기다
    assert store.get_meta(META_SYNC_ENABLED) is None  # 나머지 동기화 설정은 지워진다


def test_writes_with_a_stale_generation_are_refused_and_change_nothing(store) -> None:
    from goals import StaleSyncError

    goal = store.create(**_fields(processes=["Code.exe"]))
    old = store.generation()
    store.reset_sync()  # 에이전트 주기가 도는 사이 계정이 정리되었다

    for write in (
        lambda: store.link_remote(goal.id, "r-old", 1, expect_generation=old),
        lambda: store.mark_pushed(goal.id, 2, expect_generation=old),
        lambda: store.unlink(goal.id, expect_generation=old),
        lambda: store.set_sync_state(goal.id, "sync", expect_generation=old),
        lambda: store.clear_deletion("r-x", expect_generation=old),
        lambda: store.set_meta("account_email", "old@example.com", expect_generation=old),
        lambda: store.apply_remote(goal.id, name="낡은 값", daily_target_minutes=5, weekdays=[0], revision=9, expect_generation=old),
    ):
        with pytest.raises(StaleSyncError):
            write()

    assert _link(store, goal.id) == SyncLink(goal.id, "ask", None, None, False)  # 이전 계정의 연결이 되살아나지 않았다
    assert store.get(goal.id).name == "공부" and store.get_meta("account_email") is None


def test_writes_with_the_current_generation_go_through(store) -> None:
    goal = store.create(**_fields())
    store.reset_sync()

    store.link_remote(goal.id, "r-new", 1, expect_generation=store.generation())

    assert _link(store, goal.id).remote_id == "r-new"
