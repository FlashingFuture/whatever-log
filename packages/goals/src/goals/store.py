"""목표 저장소(goals.db, SQLite) — 목표 CRUD와 하루 스냅샷.

recorder.db와 파일을 나눈다: recorder.db는 recorder만 쓰고 hub는 읽기만 하는데, 목표는 hub와 전송
에이전트가 쓰기도 하는 사용자 설정이라 쓰기 주체가 섞이지 않게 따로 둔다. 여러 프로세스가 같은
파일을 열 수 있게 WAL 모드로 두고, 쓰기는 BEGIN IMMEDIATE로 직렬화한다. 읽기는 한 문장(SELECT 하나)
으로 끝내 다른 프로세스의 쓰기와 섞여도 일관된 결과를 본다.

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
from goals.validation import MAX_GOALS, GoalSpec, process_key, usable_keys, validate_goal

SCHEMA_VERSION = 1

# 연결 대상의 종류. 지금은 프로세스뿐이다 — 나중에 사이트 등을 더해도 저장 구조가 바뀌지 않게 종류 칸을
# 두되, CHECK로 허용 목록을 닫아 두어 모르는 종류가 들어오지 못한다.
_KIND_PROCESS = "process"

# 숫자 칸의 CHECK는 범위뿐 아니라 저장 타입도 확인한다: SQLite는 INTEGER 열에 1.5 같은 값이 들어오면
# REAL로 그대로 보관해 범위 CHECK를 통과시키고, 읽을 때 정수를 기대하는 코드가 깨진다.
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    daily_target_minutes INTEGER NOT NULL
        CHECK (typeof(daily_target_minutes) = 'integer' AND daily_target_minutes BETWEEN 1 AND 1440),
    weekdays INTEGER NOT NULL CHECK (typeof(weekdays) = 'integer' AND weekdays BETWEEN 1 AND 127),
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
    daily_target_minutes INTEGER NOT NULL
        CHECK (typeof(daily_target_minutes) = 'integer' AND daily_target_minutes BETWEEN 1 AND 1440),
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
    """요일 집합(월=0 … 일=6)을 저장용 비트 마스크로."""
    return sum(1 << day for day in weekdays)


def _weekdays_from_mask(mask: int) -> frozenset[int]:
    """저장된 비트 마스크를 요일 집합으로."""
    return frozenset(day for day in range(7) if mask & (1 << day))


def _sorted_by_key(names: list[str]) -> tuple[str, ...]:
    """프로세스 이름들을 비교 키 순으로 — Goal.processes와 GoalSnapshot.processes가 같은 순서가 되게."""
    return tuple(sorted(names, key=process_key))


class GoalStore:
    """goals.db를 여는 저장소. 쓰고 나면 close()(또는 with)로 닫는다.

    now는 시각을 만드는 함수다(테스트가 시계를 고정할 수 있게 주입한다).
    """

    def __init__(self, path: Path, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        """path의 goals.db를 열고(없으면 만들고) 스키마와 버전을 확인한다."""
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
        """with 문 진입 — 저장소 자신을 돌려준다."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """with 문을 나갈 때 연결을 닫는다."""
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
        """쓰기 트랜잭션. 다른 프로세스의 쓰기와 겹치지 않게 시작 때 잠그고, 실패하면 전부 되돌린다.

        COMMIT 자체가 실패해도(디스크 가득 참 등) 트랜잭션이 열린 채 남지 않게 되돌린 뒤 원래 오류를 올린다.
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _timestamp(self) -> str:
        """지금 시각(UTC ISO 8601)."""
        return self._now().astimezone(UTC).isoformat()

    # --- 조회 ---

    def get(self, goal_id: int) -> Goal | None:
        """id로 목표 하나. 없으면 None."""
        for goal in self.list_goals():
            if goal.id == goal_id:
                return goal
        return None

    def list_goals(self) -> list[Goal]:
        """모든 목표(만든 순서). 목표와 연결 프로세스를 한 문장으로 읽어, 다른 프로세스의 쓰기가 끼어도
        한쪽만 바뀐 결과를 보지 않는다."""
        rows = self._conn.execute(
            "SELECT g.id, g.name, g.daily_target_minutes, g.weekdays, g.created_at, g.updated_at, t.name "
            "FROM goals g LEFT JOIN goal_targets t ON t.goal_id = g.id AND t.kind = ? "
            "ORDER BY g.id",
            (_KIND_PROCESS,),
        ).fetchall()
        goals: dict[int, tuple[tuple, list[str]]] = {}
        for goal_id, name, minutes, weekdays, created_at, updated_at, process in rows:
            _, processes = goals.setdefault(
                goal_id, ((goal_id, name, minutes, weekdays, created_at, updated_at), [])
            )
            if process is not None:
                processes.append(process)
        return [
            Goal(
                id=head[0],
                name=head[1],
                daily_target_minutes=head[2],
                weekdays=_weekdays_from_mask(head[3]),
                processes=_sorted_by_key(processes),
                created_at=head[4],
                updated_at=head[5],
            )
            for head, processes in goals.values()
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
        """목표를 만든다. 입력 형식 오류와 다른 목표와의 충돌(같은 이름, 이미 연결된 프로세스, 개수 상한)을
        한꺼번에 모아 GoalValidationError로 알린다 — 사용자가 한 번에 고칠 수 있게."""
        spec, errors = self._validate(
            name, daily_target_minutes, weekdays, processes, known_processes
        )
        with self._write():
            errors += self._conflicts(name, processes, spec, errors, exclude_id=None)
            (count,) = self._conn.execute("SELECT COUNT(*) FROM goals").fetchone()
            if count >= MAX_GOALS:
                errors.append(FieldError("goals", "too_many", f"목표는 {MAX_GOALS}개까지 만들 수 있습니다."))
            if errors or spec is None:
                raise GoalValidationError(errors)
            now = self._timestamp()
            goal_id = self._conn.execute(
                "INSERT INTO goals (name, name_key, daily_target_minutes, weekdays, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (spec.name, spec.name_key, spec.daily_target_minutes, _weekday_mask(spec.weekdays), now, now),
            ).lastrowid
            self._insert_targets(goal_id, spec)
            created = self.get(goal_id)  # 같은 트랜잭션 안에서 읽는다 — 방금 저장한 상태 그대로
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

        없는 id면 GoalNotFoundError(입력 검사보다 먼저), 입력이 틀리거나 충돌하면 오류를 모아 GoalValidationError.
        """
        spec, errors = self._validate(
            name, daily_target_minutes, weekdays, processes, known_processes
        )
        with self._write():
            if self._conn.execute("SELECT 1 FROM goals WHERE id = ?", (goal_id,)).fetchone() is None:
                raise GoalNotFoundError(goal_id)
            errors += self._conflicts(name, processes, spec, errors, exclude_id=goal_id)
            if errors or spec is None:
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

    @staticmethod
    def _validate(
        name: Any,
        daily_target_minutes: Any,
        weekdays: Any,
        processes: Any,
        known_processes: Collection[str] | None,
    ) -> tuple[GoalSpec | None, list[FieldError]]:
        """입력 형식 검증. 통과하면 (GoalSpec, []), 실패하면 (None, 오류들) — 충돌 검사와 합쳐 알리려고 예외 대신 돌려준다."""
        try:
            return (
                validate_goal(
                    name=name,
                    daily_target_minutes=daily_target_minutes,
                    weekdays=weekdays,
                    processes=processes,
                    known_processes=known_processes,
                ),
                [],
            )
        except GoalValidationError as error:
            return None, list(error.errors)

    def _insert_targets(self, goal_id: int, spec: GoalSpec) -> None:
        """목표의 연결 프로세스들을 저장한다."""
        self._conn.executemany(
            "INSERT INTO goal_targets (goal_id, kind, name, name_key) VALUES (?, ?, ?, ?)",
            [(goal_id, _KIND_PROCESS, name, key) for name, key in spec.processes],
        )

    def _conflicts(
        self,
        raw_name: Any,
        raw_processes: Any,
        spec: GoalSpec | None,
        format_errors: list[FieldError],
        *,
        exclude_id: int | None,
    ) -> list[FieldError]:
        """다른 목표와 겹치는 것(같은 이름, 이미 다른 목표에 연결된 프로세스)을 오류로 모은다.

        형식 검증을 통과했으면 그 값을, 실패했으면 형식이 맞는 부분만(usable_keys) 확인해서 형식 오류와
        충돌을 같이 알릴 수 있게 한다.
        """
        if spec is not None:
            key, pairs = spec.name_key, list(spec.processes)
        else:
            key, pairs = usable_keys(raw_name, raw_processes, format_errors)
        errors: list[FieldError] = []
        exclude = -1 if exclude_id is None else exclude_id
        if (
            key is not None
            and self._conn.execute(
                "SELECT 1 FROM goals WHERE name_key = ? AND id != ?", (key, exclude)
            ).fetchone()
        ):
            errors.append(FieldError("name", "duplicate", "같은 이름의 목표가 이미 있습니다."))

        linked: list[str] = []
        for name, process in pairs:
            row = self._conn.execute(
                "SELECT goals.name FROM goal_targets JOIN goals ON goals.id = goal_targets.goal_id "
                "WHERE goal_targets.kind = ? AND goal_targets.name_key = ? AND goal_targets.goal_id != ?",
                (_KIND_PROCESS, process, exclude),
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

        목표를 바꿔도 지난 날의 달성률이 같이 바뀌지 않게 하려는 것이다. 오늘의 스냅샷은 그날 안에서
        목표를 고칠 때마다 다시 기록되고, 날짜가 지나면 확정된다. 오늘 요일에 적용되지 않는 목표는
        기록하지 않는다. 호출부는 "오늘"을 **로컬 시간대**로 정해 넘긴다(이 패키지는 시간대를 모른다).

        잘못된 날짜가 확정된 기록을 덮어쓰지 못하게 두 가지를 막는다(ValueError):
        - 이미 기록된 가장 늦은 날짜보다 이른 날짜(지난 날은 확정이다).
        - 시계의 UTC 날짜와 하루를 넘게 차이 나는 날짜(어느 시간대의 "오늘"이어도 UTC 날짜와 하루
          안쪽이므로, 그보다 먼 날짜는 호출부의 실수다).
        """
        if not isinstance(today, date) or isinstance(today, datetime):
            raise ValueError("today는 날짜(date)여야 합니다.")
        clock_day = self._now().astimezone(UTC).date()
        if abs((today - clock_day).days) > 1:
            raise ValueError("today가 시계의 날짜와 하루를 넘게 차이 납니다. 로컬 날짜를 넘겨 주세요.")
        day = today.isoformat()
        recorded_at = self._timestamp()
        with self._write():
            (latest,) = self._conn.execute("SELECT MAX(day) FROM goal_snapshots").fetchone()
            if latest is not None and day < latest:
                raise ValueError(f"{latest}까지 기록된 스냅샷이 있어 더 이른 날({day})은 바꿀 수 없습니다(지난 날은 확정).")
            self._conn.execute("DELETE FROM goal_snapshots WHERE day = ?", (day,))
            for goal in self.list_goals():
                if today.weekday() not in goal.weekdays:
                    continue
                self._conn.execute(
                    "INSERT INTO goal_snapshots (day, goal_id, name, daily_target_minutes, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (day, goal.id, goal.name, goal.daily_target_minutes, recorded_at),
                )
                self._conn.executemany(
                    "INSERT INTO goal_snapshot_targets (day, goal_id, kind, name) VALUES (?, ?, ?, ?)",
                    [(day, goal.id, _KIND_PROCESS, process) for process in goal.processes],
                )
        return self.snapshots(today)

    def snapshots(self, day: date) -> list[GoalSnapshot]:
        """그날의 스냅샷들(목표 id 순). 기록이 없으면 빈 목록. 한 문장으로 읽어 일관된 결과를 본다."""
        rows = self._conn.execute(
            "SELECT s.goal_id, s.name, s.daily_target_minutes, t.name "
            "FROM goal_snapshots s "
            "LEFT JOIN goal_snapshot_targets t ON t.day = s.day AND t.goal_id = s.goal_id AND t.kind = ? "
            "WHERE s.day = ? ORDER BY s.goal_id",
            (_KIND_PROCESS, day.isoformat()),
        ).fetchall()
        grouped: dict[int, tuple[str, int, list[str]]] = {}
        for goal_id, name, minutes, process in rows:
            _, _, processes = grouped.setdefault(goal_id, (name, minutes, []))
            if process is not None:
                processes.append(process)
        return [
            GoalSnapshot(
                day=day,
                goal_id=goal_id,
                name=name,
                daily_target_minutes=minutes,
                processes=_sorted_by_key(processes),
            )
            for goal_id, (name, minutes, processes) in grouped.items()
        ]
