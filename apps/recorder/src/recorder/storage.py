"""TickSample을 SQLite에 저장한다.

docs/recorder-sqlite-design.md의 결정을 그대로 구현한다:

- WAL 모드 + synchronous=NORMAL — 앱 크래시(프로세스 kill 등)에는 안전하면서도
  매 틱 커밋 오버헤드를 최소화한다. (synchronous=NORMAL이 WAL 모드에서 잃을 수
  있는 건 OS/전원 장애 시 가장 마지막 커밋 1개 뿐이다 — 우리가 막으려는
  "프로세스가 죽는" 상황에는 영향 없음.)
- 파라미터 바인딩만 사용 — 문자열 포매팅으로 SQL을 만들지 않는다(인젝션 방지).
  프로세스 이름은 OS에서 온 값이라 대체로 안전하지만, 바인딩을 안 쓸 이유가 없다.
- foreign_keys를 명시적으로 켠다 — SQLite는 기본값이 꺼짐이라, 안 켜면
  tick_windowed_processes가 존재하지 않는 tick_id를 참조해도 막히지 않는다.
- 틱당 ticks 1행 + tick_windowed_processes N행(윈도우 프로세스 개수만큼, 틱당
  연산이 가장 많이 발생하는 부분)을 하나의 트랜잭션으로 묶어서 커밋 1번으로
  처리한다. N개를 executemany로 한 번에 보내서 Python↔SQLite 왕복도 줄인다.

나중에 파일 전체 암호화(SQLCipher)가 필요해지면 여기(open_db)만 바꾸면 된다 —
스키마나 save_tick은 그대로 둬도 된다.
"""

import sqlite3
from pathlib import Path

from recorder.sampling import TickSample

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY,
    sampled_at TEXT NOT NULL,
    foreground_process TEXT,
    seconds_since_last_input REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tick_windowed_processes (
    tick_id INTEGER NOT NULL REFERENCES ticks(id) ON DELETE CASCADE,
    process_name TEXT NOT NULL,
    PRIMARY KEY (tick_id, process_name)
);

CREATE INDEX IF NOT EXISTS idx_ticks_sampled_at ON ticks(sampled_at);
CREATE INDEX IF NOT EXISTS idx_ticks_foreground_process ON ticks(foreground_process);
CREATE INDEX IF NOT EXISTS idx_tick_windowed_processes_name
    ON tick_windowed_processes(process_name);
"""


def open_db(path: Path) -> sqlite3.Connection:
    """DB를 열고(없으면 파일/스키마 생성) PRAGMA를 맞춘 커넥션을 반환한다.

    isolation_level=None으로 autocommit 모드를 쓴다 — 트랜잭션 경계를
    save_tick()에서 BEGIN/COMMIT/ROLLBACK으로 직접, 명시적으로 관리하기 위함.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


def save_tick(conn: sqlite3.Connection, sample: TickSample) -> None:
    """한 틱을 하나의 트랜잭션으로 저장한다. 실패하면 전부 롤백한다."""
    conn.execute("BEGIN")
    try:
        cursor = conn.execute(
            "INSERT INTO ticks (sampled_at, foreground_process, seconds_since_last_input) "
            "VALUES (?, ?, ?)",
            (
                sample.sampled_at.isoformat(),
                sample.foreground_process,
                sample.seconds_since_last_input,
            ),
        )
        tick_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO tick_windowed_processes (tick_id, process_name) VALUES (?, ?)",
            [(tick_id, name) for name in sample.windowed_processes],
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
