import sqlite3

import pytest

from goalsync import peek_device_id


def test_peeking_the_device_id_never_creates_the_agents_file(tmp_path) -> None:
    path = tmp_path / "sync.db"

    assert peek_device_id(path) is None
    assert not path.exists()


def test_peeking_reads_the_id_the_agent_made_and_is_read_only(tmp_path) -> None:
    from goalsync import SyncState

    path = tmp_path / "sync.db"
    with SyncState(path) as state:
        made = state.device_id()

    assert peek_device_id(path) == made
    raw = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        raw.execute("INSERT INTO device (id, device_id) VALUES (2, 'x')")
    raw.close()


def test_peeking_a_file_without_the_schema_is_none(tmp_path) -> None:
    path = tmp_path / "sync.db"
    sqlite3.connect(path).close()

    assert peek_device_id(path) is None
