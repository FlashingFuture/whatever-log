"""목표 저장소(goals.db, SQLite) — 목표 CRUD와 하루 스냅샷.

recorder.db와 파일을 나눈다: recorder.db는 recorder만 쓰고 hub는 읽기만 하는데, 목표는 hub와 전송
에이전트가 쓰기도 하는 사용자 설정이라 쓰기 주체가 섞이지 않게 따로 둔다. 여러 프로세스가 같은
파일을 열 수 있게 WAL 모드로 두고, 쓰기는 BEGIN IMMEDIATE로 직렬화한다.

규칙은 두 겹으로 지킨다: 입력은 validation.validate_goal이 엄격하게 검증하고, 스키마의 제약
(CHECK·UNIQUE)이 그 규칙의 마지막 방어선이다. 특히 "한 프로세스는 하나의 목표에만"은 UNIQUE로 막아,
검증을 거치지 않은 경로가 생겨도 지켜진다.
"""

import sqlite3
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from goals.errors import FieldError, GoalNotFoundError, GoalValidationError, SchemaVersionError
from goals.models import Goal, GoalSnapshot
from goals.validation import MAX_GOALS, GoalSpec, validate_goal

SCHEMA_VERSION = 1

# 연결 대상의 종류. 지금은 프로세스뿐이다 — 나중에 사이트 등을 더해도 저장 구조가 바뀌지 않게 종류 칸을
# 두되, CHECK로 허용 목록을 닫아 두어 모르는 종류가 들어오지 못한다.
_KIND_PROCESS = "process"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    daily_target_minutes INTEGER NOT NULL CHECK (daily_target_minutes BETWEEN 1 AND 1440),
    weekdays INTEGER NOT NULL CHECK (weekdays BETWEEN 1 AND 127),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_targets (
    goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('{_KIND_PROCESS}')),
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    PRIMARY KEY (goal_id, kind, name_key),
    UNIQUE (kind, name_key)
);

-- 어떤 날짜에 적용된 목표 설정의 기록(지난 날은 바뀌지 않는다). 목표가 나중에 삭제돼도 남도록 goals에 묶지 않는다.
CREATE TABLE IF NOT EXISTS goal_snapshots (
    day TEXT NOT NULL,
    goal_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    daily_target_minutes INTEGER NOT NULL CHECK (daily_target_minutes BETWEEN 1 AND 1440),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (day, goal_id)
);

CREATE TABLE IF NOT EXISTS goal_snapshot_targets (
    day TEXT NOT NULL,
    goal_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('{_KIND_PROCESS}')),
    name TEXT NOT NULL,
    PRIMARY KEY (day, goal_id, kind, name),
    FOREIGN KEY (day, goal_id) REFERENCES goal_snapshots(day, goal_id) ON DELETE CASCADE
);
"""


def _weekday_mask(weekdays: frozenset[int]) -> int:
    return sum(1 << day for day in weekdays)


def _weekdays_from_mask(mask: int) -> frozenset[int]:
    return frozenset(day for day in range(7) if mask & (1 << day))


class GoalStore:
    """goals.db를 여는 저장소. 쓰고 나면 close()(또는 with)로 닫는다.

    now는 시각을 만드는 함수다(테스트가 시계를 고정할 수 있게 주입한다).
    """

    def __init__(self, path: Path, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._now = now
        self._conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._prepare_schema()
        except BaseException:
            self._conn.close()
            raise

    def close(self) -> None:
        """연결을 닫는다."""
        self._conn.close()

    def __enter__(self) -> "GoalStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _prepare_schema(self) -> None:
        """스키마를 만들거나 버전을 확인한다. 이 코드보다 새 버전의 파일은 거부한다."""
        (version,) = self._conn.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"goals.db가 더 새로운 버전({version})으로 만들어졌습니다. 이 프로그램은 {SCHEMA_VERSION}까지 다룹니다."
            )
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @contextmanager
    def _write(self) -> Iterator[None]:
        """쓰기 트랜잭션. 다른 프로세스의 쓰기와 겹치지 않게 시작 때 잠그고, 실패하면 전부 되돌린다."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def _timestamp(self) -> str:
        return self._now().astimezone(UTC).isoformat()

    # --- 조회 ---

    def get(self, goal_id: int) -> Goal | None:
        """id로 목표 하나. 없으면 None."""
        for goal in self.list_goals():
            if goal.id == goal_id:
                return goal
        return None

    def list_goals(self) -> list[Goal]:
        """모든 목표(만든 순서)."""
        targets: dict[int, list[str]] = {}
        for goal_id, name in self._conn.execute(
            "SELECT goal_id, name FROM goal_targets WHERE kind = ? ORDER BY name_key", (_KIND_PROCESS,)
        ):
            targets.setdefault(goal_id, []).append(name)
        return [
            Goal(
                id=row[0],
                name=row[1],
                daily_target_minutes=row[2],
                weekdays=_weekdays_from_mask(row[3]),
                processes=tuple(targets.get(row[0], [])),
                created_at=row[4],
                updated_at=row[5],
            )
            for row in self._conn.execute(
                "SELECT id, name, daily_target_minutes, weekdays, created_at, updated_at FROM goals ORDER BY id"
            )
        ]

    # --- 변경 ---

    def create(
        self,
        *,
        name: Any,
        daily_target_minutes: Any,
        weekdays: Any,
        processes: Any,
        known_processes: Collection[str] | None = None,
    ) -> Goal:
        """검증을 거쳐 목표를 만든다. 검증·충돌 오류는 GoalValidationError(모든 칸의 오류를 담음)."""
        spec = validate_goal(
            name=name,
            daily_target_minutes=daily_target_minutes,
            weekdays=weekdays,
            processes=processes,
            known_processes=known_processes,
        )
        with self._write():
            errors = self._conflicts(spec, exclude_id=None)
            (count,) = self._conn.execute("SELECT COUNT(*) FROM goals").fetchone()
            if count >= MAX_GOALS:
                errors.append(FieldError("goals", "too_many", f"목표는 {MAX_GOALS}개까지 만들 수 있습니다."))
            if errors:
                raise GoalValidationError(errors)
            now = self._timestamp()
            goal_id = self._conn.execute(
                "INSERT INTO goals (name, name_key, daily_target_minutes, weekdays, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (spec.name, spec.name_key, spec.daily_target_minutes, _weekday_mask(spec.weekdays), now, now),
            ).lastrowid
            self._insert_targets(goal_id, spec)
        created = self.get(goal_id)
        assert created is not None
        return created

    def update(
        self,
        goal_id: int,
        *,
        name: Any,
        daily_target_minutes: Any,
        weekdays: Any,
        processes: Any,
        known_processes: Collection[str] | None = None,
    ) -> Goal:
        """목표를 통째로 바꾼다(모든 칸이 필요하다 — 일부만 바꾸는 입력은 받지 않는다).

        없는 id면 GoalNotFoundError, 입력이 틀리면 GoalValidationError.
        """
        spec = validate_goal(
            name=name,
            daily_target_minutes=daily_target_minutes,
            weekdays=weekdays,
            processes=processes,
            known_processes=known_processes,
        )
        with self._write():
            if self._conn.execute("SELECT 1 FROM goals WHERE id = ?", (goal_id,)).fetchone() is None:
                raise GoalNotFoundError(goal_id)
            errors = self._conflicts(spec, exclude_id=goal_id)
            if errors:
                raise GoalValidationError(errors)
            self._conn.execute(
                "UPDATE goals SET name = ?, name_key = ?, daily_target_minutes = ?, weekdays = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    spec.name,
                    spec.name_key,
                    spec.daily_target_minutes,
                    _weekday_mask(spec.weekdays),
                    self._timestamp(),
                    goal_id,
                ),
            )
            self._conn.execute("DELETE FROM goal_targets WHERE goal_id = ?", (goal_id,))
            self._insert_targets(goal_id, spec)
        updated = self.get(goal_id)
        assert updated is not None
        return updated

    def delete(self, goal_id: int) -> None:
        """목표를 지운다(연결 정보도 같이). 지난 날의 스냅샷은 남는다. 없는 id면 GoalNotFoundError."""
        with self._write():
            deleted = self._conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,)).rowcount
            if deleted == 0:
                raise GoalNotFoundError(goal_id)

    def _insert_targets(self, goal_id: int, spec: GoalSpec) -> None:
        self._conn.executemany(
            "INSERT INTO goal_targets (goal_id, kind, name, name_key) VALUES (?, ?, ?, ?)",
            [(goal_id, _KIND_PROCESS, name, key) for name, key in spec.processes],
        )

    def _conflicts(self, spec: GoalSpec, *, exclude_id: int | None) -> list[FieldError]:
        """다른 목표와 겹치는 것(같은 이름, 이미 다른 목표에 연결된 프로세스)을 오류로 모은다."""
        errors: list[FieldError] = []
        exclude = -1 if exclude_id is None else exclude_id
        if self._conn.execute(
            "SELECT 1 FROM goals WHERE name_key = ? AND id != ?", (spec.name_key, exclude)
        ).fetchone():
            errors.append(FieldError("name", "duplicate", "같은 이름의 목표가 이미 있습니다."))

        linked: list[str] = []
        for name, key in spec.processes:
            row = self._conn.execute(
                "SELECT goals.name FROM goal_targets JOIN goals ON goals.id = goal_targets.goal_id "
                "WHERE goal_targets.kind = ? AND goal_targets.name_key = ? AND goal_targets.goal_id != ?",
                (_KIND_PROCESS, key, exclude),
            ).fetchone()
            if row:
                linked.append(f"`{name}`(`{row[0]}` 목표)")
        if linked:
            errors.append(
                FieldError(
                    "processes",
                    "already_linked",
                    "이미 다른 목표에 연결된 프로세스입니다: " + ", ".join(linked),
                )
            )
        return errors

    # --- 하루 스냅샷 ---

    def snapshot_today(self, today: date) -> list[GoalSnapshot]:
        """오늘 적용되는 목표들의 현재 설정을 오늘의 스냅샷으로 기록한다(이미 있으면 덮어쓴다).

        목표를 바꿔도 지난 날의 달성률이 같이 바뀌지 않게 하려는 것이다. 규칙은 단순하다: 오늘의 스냅샷은
        그날 안에서 목표를 고칠 때마다 최신 설정으로 다시 기록되고, 날짜가 지나면 이 함수가 더는 그날을
        건드리지 않아 확정된다(지난 날짜는 아예 받지 않는다). 오늘 요일에 적용되지 않는 목표는 기록하지
        않는다. 호출부는 "오늘"을 로컬 시간대로 정해 넘긴다(이 패키지는 시간대를 모른다).
        """
        if not isinstance(today, date) or isinstance(today, datetime):
            raise ValueError("today는 날짜(date)여야 합니다.")
        day = today
        recorded_at = self._timestamp()
        with self._write():
            self._conn.execute("DELETE FROM goal_snapshots WHERE day = ?", (day.isoformat(),))
            for goal in self.list_goals():
                if day.weekday() not in goal.weekdays:
                    continue
                self._conn.execute(
                    "INSERT INTO goal_snapshots (day, goal_id, name, daily_target_minutes, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (day.isoformat(), goal.id, goal.name, goal.daily_target_minutes, recorded_at),
                )
                self._conn.executemany(
                    "INSERT INTO goal_snapshot_targets (day, goal_id, kind, name) VALUES (?, ?, ?, ?)",
                    [(day.isoformat(), goal.id, _KIND_PROCESS, process) for process in goal.processes],
                )
        return self.snapshots(day)

    def snapshots(self, day: date) -> list[GoalSnapshot]:
        """그날의 스냅샷들(목표 id 순). 기록이 없으면 빈 목록."""
        targets: dict[int, list[str]] = {}
        for goal_id, name in self._conn.execute(
            "SELECT goal_id, name FROM goal_snapshot_targets WHERE day = ? AND kind = ? ORDER BY name COLLATE NOCASE",
            (day.isoformat(), _KIND_PROCESS),
        ):
            targets.setdefault(goal_id, []).append(name)
        return [
            GoalSnapshot(
                day=day,
                goal_id=row[0],
                name=row[1],
                daily_target_minutes=row[2],
                processes=tuple(targets.get(row[0], [])),
            )
            for row in self._conn.execute(
                "SELECT goal_id, name, daily_target_minutes FROM goal_snapshots WHERE day = ? ORDER BY goal_id",
                (day.isoformat(),),
            )
        ]
