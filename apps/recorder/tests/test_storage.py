import sqlite3
from datetime import UTC, datetime

import pytest

from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick


def test_save_tick_persists_ticks_and_windowed_processes(tmp_path) -> None:
    conn = open_db(tmp_path / "test.db")
    sample = TickSample(
        sampled_at=datetime(2026, 1, 1, tzinfo=UTC),
        foreground_process="Code.exe",
        windowed_processes=frozenset({"Code.exe", "chrome.exe"}),
        seconds_since_last_input=1.5,
    )

    save_tick(conn, sample)

    tick_row = conn.execute(
        "SELECT foreground_process, seconds_since_last_input FROM ticks"
    ).fetchone()
    assert tick_row == ("Code.exe", 1.5)

    windowed = {
        row[0] for row in conn.execute("SELECT process_name FROM tick_windowed_processes")
    }
    assert windowed == {"Code.exe", "chrome.exe"}


def test_save_tick_allows_null_foreground_process(tmp_path) -> None:
    conn = open_db(tmp_path / "test.db")
    sample = TickSample(
        sampled_at=datetime(2026, 1, 1, tzinfo=UTC),
        foreground_process=None,
        windowed_processes=frozenset(),
        seconds_since_last_input=0.0,
    )

    save_tick(conn, sample)

    foreground = conn.execute("SELECT foreground_process FROM ticks").fetchone()[0]
    assert foreground is None


def test_foreign_keys_are_enforced(tmp_path) -> None:
    conn = open_db(tmp_path / "test.db")

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tick_windowed_processes (tick_id, process_name) VALUES (?, ?)",
            (999, "ghost.exe"),
        )


def test_each_tick_commits_as_one_transaction(tmp_path) -> None:
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
