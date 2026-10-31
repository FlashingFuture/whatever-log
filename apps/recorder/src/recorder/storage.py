"""TickSample을 SQLite에 저장한다.

docs/recorder-sqlite-design.md의 결정을 그대로 구현한다:

- WAL 모드 + synchronous=NORMAL — 앱 크래시(프로세스 kill 등)에는 안전하면서도
  매 틱 커밋 오버헤드를 최소화한다. (synchronous=NORMAL이 WAL 모드에서 잃을 수
  있는 건 OS/전원 장애 시 가장 마지막 커밋 1개 뿐이다 — 우리가 막으려는
  "프로세스가 죽는" 상황에는 영향 없음.)
- 파라미터 바인딩만 사용 — 문자열 포매팅으로 SQL을 만들지 않는다(인젝션 방지).
  프로세스 이름은 OS에서 온 값이라 대체로 안전하지만, 바인딩을 안 쓸 이유가 없다.
- foreign_keys를 명시적으로 켠다 — SQLite는 기본값이 꺼짐이라, 안 켜면
  tick_windowed_processes/ticks가 존재하지 않는 process_id를 참조해도 막히지
  않는다.
- 프로세스 이름은 processes 테이블에 한 번만 저장하고 나머지는 정수 id로
  참조한다 (같은 프로세스가 매 틱 반복돼도 문자열을 반복 저장하지 않음).
- 틱당 ticks 1행 + tick_windowed_processes N행(윈도우 프로세스 개수만큼, 틱당
  연산이 가장 많이 발생하는 부분)을 하나의 트랜잭션으로 묶어서 커밋 1번으로
  처리한다.

나중에 파일 전체 암호화(SQLCipher)가 필요해지면 여기(open_db)만 바꾸면 된다 —
스키마나 save_tick은 그대로 둬도 된다.
"""

import sqlite3
from pathlib import Path

from recorder.sampling import TickSample

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    exe_path TEXT
);

CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY,
    sampled_at TEXT NOT NULL,
    foreground_process_id INTEGER REFERENCES processes(id),
    seconds_since_last_input REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tick_windowed_processes (
    tick_id INTEGER NOT NULL REFERENCES ticks(id) ON DELETE CASCADE,
    process_id INTEGER NOT NULL REFERENCES processes(id),
    PRIMARY KEY (tick_id, process_id)
);

CREATE INDEX IF NOT EXISTS idx_ticks_sampled_at ON ticks(sampled_at);
CREATE INDEX IF NOT EXISTS idx_ticks_foreground_process_id ON ticks(foreground_process_id);
CREATE INDEX IF NOT EXISTS idx_tick_windowed_processes_process_id
    ON tick_windowed_processes(process_id);
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
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """이미 만들어진 DB에 뒤늦게 추가된 컬럼을 채워 넣는다.

    CREATE TABLE IF NOT EXISTS는 있는 테이블을 고치지 않으므로, 예전 recorder가
    만든 DB에는 exe_path가 없다.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(processes)")}
    if "exe_path" not in columns:
        conn.execute("ALTER TABLE processes ADD COLUMN exe_path TEXT")


def _get_or_create_process_id(conn: sqlite3.Connection, name: str) -> int:
    """process 이름으로 id를 가져온다. 없으면 만들어서 반환한다 (get-or-create).

    DO NOTHING이 아니라 DO UPDATE를 쓰는 이유: SQLite는 ON CONFLICT DO NOTHING이면
    RETURNING이 아무 것도 안 돌려준다. DO UPDATE(사실상 no-op)여야 충돌이 나도
    행이 "갱신됐다"고 취급되어 RETURNING으로 id를 받을 수 있다.
    """
    row = conn.execute(
        "INSERT INTO processes (name) VALUES (?) "
        "ON CONFLICT(name) DO UPDATE SET name = name "
        "RETURNING id",
        (name,),
    ).fetchone()
    return row[0]


def save_tick(conn: sqlite3.Connection, sample: TickSample) -> None:
    """한 틱을 하나의 트랜잭션으로 저장한다. 실패하면 전부 롤백한다."""
    conn.execute("BEGIN")
    try:
        foreground_process_id = (
            _get_or_create_process_id(conn, sample.foreground_process)
            if sample.foreground_process is not None
            else None
        )

        cursor = conn.execute(
            "INSERT INTO ticks (sampled_at, foreground_process_id, seconds_since_last_input) "
            "VALUES (?, ?, ?)",
            (
                sample.sampled_at.isoformat(),
                foreground_process_id,
                sample.seconds_since_last_input,
            ),
        )
        tick_id = cursor.lastrowid

        windowed_rows = [
            (tick_id, _get_or_create_process_id(conn, name))
            for name in sample.windowed_processes
        ]
        conn.executemany(
            "INSERT INTO tick_windowed_processes (tick_id, process_id) VALUES (?, ?)",
            windowed_rows,
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def save_process_paths(conn: sqlite3.Connection, paths: dict[str, str]) -> None:
    """{프로세스 이름: exe 경로}를 processes에 기록한다.

    경로가 바뀐 경우(앱 업데이트로 폴더가 바뀌는 등)에는 새 값으로 덮어쓴다.
    같은 값이면 쓰지 않는다. 아직 틱에 나온 적 없는 이름은 행이 없어 무시된다 —
    호출부는 save_tick() 뒤에 부른다.
    """
    conn.executemany(
        "UPDATE processes SET exe_path = ? "
        "WHERE name = ? AND (exe_path IS NULL OR exe_path != ?)",
        [(path, name, path) for name, path in paths.items()],
    )
