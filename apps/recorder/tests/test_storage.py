import sqlite3
from datetime import UTC, datetime

import pytest

from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick


def _process_name(conn: sqlite3.Connection, process_id: int) -> str:
    return conn.execute(
        "SELECT name FROM processes WHERE id = ?", (process_id,)
    ).fetchone()[0]


def test_save_tick_persists_ticks_and_windowed_processes(tmp_path) -> None:
    """ticks/tick_windowed_processes에 id가 processes의 올바른 이름으로 풀리는지 확인."""
    conn = open_db(tmp_path / "test.db")
    sample = TickSample(
        sampled_at=datetime(2026, 1, 1, tzinfo=UTC),
        foreground_process="Code.exe",
        windowed_processes=frozenset({"Code.exe", "chrome.exe"}),
        seconds_since_last_input=1.5,
    )

    save_tick(conn, sample)

    foreground_process_id, idle = conn.execute(
        "SELECT foreground_process_id, seconds_since_last_input FROM ticks"
    ).fetchone()
    assert _process_name(conn, foreground_process_id) == "Code.exe"
    assert idle == 1.5

    windowed = {
        _process_name(conn, row[0])
        for row in conn.execute("SELECT process_id FROM tick_windowed_processes")
    }
    assert windowed == {"Code.exe", "chrome.exe"}


def test_save_tick_allows_null_foreground_process(tmp_path) -> None:
    """foreground_process가 None이어도 DB 제약(NOT NULL 등)에 안 걸려야 한다."""
    conn = open_db(tmp_path / "test.db")
    sample = TickSample(
        sampled_at=datetime(2026, 1, 1, tzinfo=UTC),
        foreground_process=None,
        windowed_processes=frozenset(),
        seconds_since_last_input=0.0,
    )

    save_tick(conn, sample)

    foreground_process_id = conn.execute(
        "SELECT foreground_process_id FROM ticks"
    ).fetchone()[0]
    assert foreground_process_id is None


def test_same_process_name_reuses_the_same_process_id(tmp_path) -> None:
    """같은 프로세스가 여러 틱에 걸쳐 나와도 processes 테이블에 한 행만 생겨야 한다."""
    conn = open_db(tmp_path / "test.db")
    sample = TickSample(
        sampled_at=datetime(2026, 1, 1, tzinfo=UTC),
        foreground_process="Code.exe",
        windowed_processes=frozenset({"Code.exe"}),
        seconds_since_last_input=0.0,
    )

    save_tick(conn, sample)
    save_tick(conn, sample)
    save_tick(conn, sample)

    process_count = conn.execute(
        "SELECT COUNT(*) FROM processes WHERE name = 'Code.exe'"
    ).fetchone()[0]
    tick_count = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
    assert process_count == 1
    assert tick_count == 3


def test_foreign_keys_are_enforced(tmp_path) -> None:
    """PRAGMA foreign_keys = ON이 실제로 걸려있는지 확인 (SQLite는 기본이 꺼짐)."""
    conn = open_db(tmp_path / "test.db")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tick_windowed_processes (tick_id, process_id) VALUES (?, ?)",
            (999, 1),
        )


def test_each_tick_commits_as_one_transaction(tmp_path) -> None:
    """윈도우 프로세스가 몇 개든 한 틱 = ticks 1행 + 그만큼의 연결 행이어야 한다."""
    conn = open_db(tmp_path / "test.db")
    sample = TickSample(
        sampled_at=datetime(2026, 1, 1, tzinfo=UTC),
        foreground_process="a.exe",
        windowed_processes=frozenset({"a.exe", "b.exe", "c.exe"}),
        seconds_since_last_input=0.0,
    )

    save_tick(conn, sample)

    tick_count = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
    windowed_count = conn.execute("SELECT COUNT(*) FROM tick_windowed_processes").fetchone()[0]
    assert tick_count == 1
    assert windowed_count == 3
