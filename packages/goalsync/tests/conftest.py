from collections.abc import Collection
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from cloud import GoalConflict, ProgressResult, RemoteGoal, ServerError, ServerUnreachable
from goals import GoalStore
from goals.validation import name_key
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from goalsync import SyncState

TODAY = date(2026, 11, 5)


class FakeServer:
    """서버의 목표·달성도 규칙을 메모리에서 흉내 낸다(apps/server의 규칙과 같게 — 실제 서버와의 일치는 e2e 시험이 본다)."""

    def __init__(self) -> None:
        self.goals: dict[str, RemoteGoal] = {}
        self.progress: dict[tuple[str, str, str], tuple[int, int]] = {}
        self.calls: list[str] = []
        self.unreachable = False
        self.limit = 20

    def _enter(self, call: str) -> None:
        self.calls.append(call)
        if self.unreachable:
            raise ServerUnreachable

    def _live(self) -> list[RemoteGoal]:
        return [goal for goal in self.goals.values() if not goal.deleted]

    # --- 다른 기기의 행동을 흉내 내는 보조 ---
    def add(self, goal_id: str, name: str, minutes: int = 60, weekdays=(0, 1, 2, 3, 4), revision: int = 1) -> RemoteGoal:
        goal = RemoteGoal(goal_id, False, revision, "t", name, minutes, frozenset(weekdays))
        self.goals[goal_id] = goal
        return goal

    def edit(self, goal_id: str, **changes) -> None:
        old = self.goals[goal_id]
        values = {
            "name": old.name,
            "daily_target_minutes": old.daily_target_minutes,
            "weekdays": old.weekdays,
            **changes,
        }
        self.goals[goal_id] = RemoteGoal(goal_id, False, old.revision + 1, "t", **values)

    def remove(self, goal_id: str) -> None:
        old = self.goals[goal_id]
        self.goals[goal_id] = RemoteGoal(goal_id, True, old.revision + 1, "t")

    def forget(self, goal_id: str) -> None:
        del self.goals[goal_id]

    # --- ServerApi와 같은 메서드 ---
    def list_goals(self) -> list[RemoteGoal]:
        self._enter("list_goals")
        return list(self.goals.values())

    def put_goal(
        self, goal_id: str, *, name: str, daily_target_minutes: int, weekdays: Collection[int], base_revision: int
    ) -> RemoteGoal:
        self._enter(f"put_goal:{base_revision}")
        existing = self.goals.get(goal_id)
        clash = any(
            goal.id != goal_id and name_key(goal.name or "") == name_key(name) for goal in self._live()
        )
        if base_revision == 0:
            if existing is not None:
                code = "goal_deleted" if existing.deleted else "conflict"
                raise GoalConflict(code, "이미 있는 목표입니다.", existing)
            if clash:
                raise GoalConflict("duplicate_name", "같은 이름의 목표가 이미 있습니다.", None)
            if len(self._live()) >= self.limit:
                raise GoalConflict("too_many_goals", "목표는 20개까지 만들 수 있습니다.", None)
            revision = 1
        else:
            if existing is None:
                raise ServerError(404, "not_found", "없는 목표입니다.")
            if existing.deleted:
                raise GoalConflict("goal_deleted", "삭제된 목표입니다.", existing)
            if existing.revision != base_revision:
                raise GoalConflict("conflict", "다른 기기에서 먼저 바뀌었습니다.", existing)
            if clash:
                raise GoalConflict("duplicate_name", "같은 이름의 목표가 이미 있습니다.", None)
            revision = existing.revision + 1
        goal = RemoteGoal(goal_id, False, revision, "t", name, daily_target_minutes, frozenset(weekdays))
        self.goals[goal_id] = goal
        return goal

    def delete_goal(self, goal_id: str) -> bool:
        self._enter("delete_goal")
        if goal_id not in self.goals:
            return False
        if not self.goals[goal_id].deleted:
            self.remove(goal_id)
        return True

    def put_progress(self, device_id: str, entries) -> ProgressResult:
        self._enter("put_progress")
        ignored = []
        accepted = 0
        for entry in entries:
            goal = self.goals.get(entry.goal_id)
            if goal is None or goal.deleted:
                ignored.append(entry.goal_id)
                continue
            self.progress[(entry.goal_id, device_id, entry.day)] = (entry.minutes, entry.target_minutes)
            accepted += 1
        return ProgressResult(accepted, tuple(ignored))


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def store(tmp_path):
    clock = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)
    with GoalStore(tmp_path / "goals.db", now=lambda: clock) as opened:
        yield opened


@pytest.fixture
def state(tmp_path):
    with SyncState(tmp_path / "sync.db") as opened:
        yield opened


def goal_fields(**overrides):
    fields = {"name": "공부", "daily_target_minutes": 120, "weekdays": [0, 1, 2, 3, 4], "processes": []}
    fields.update(overrides)
    return fields


def make_recorder_db(path: Path, ticks: dict[date, list[tuple[str, int]]]) -> Path:
    """로컬 날짜별로 (프로세스, 15초 틱 수)를 정오부터 이어 붙여 recorder.db를 만든다. 사이트는 `process:domain`으로 줄 수 있다."""
    conn = open_db(path)
    for day, runs in ticks.items():
        moment = datetime.combine(day, time(12, 0)).astimezone()
        for spec, count in runs:
            process, _, site = spec.partition(":")
            for _ in range(count + 1):  # 마지막 틱은 집계에서 빠지므로 하나 더 둔다
                save_tick(
                    conn,
                    TickSample(
                        sampled_at=moment.astimezone(UTC),
                        foreground_process=process,
                        windowed_processes=frozenset({process}),
                        seconds_since_last_input=0.0,
                        foreground_site=site or None,
                    ),
                )
                moment += timedelta(seconds=15)
    conn.close()
    return path
