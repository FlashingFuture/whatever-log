import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from launcher import components, data_import


def _make_db(path: Path, table: str, rows: int, *, wal: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"CREATE TABLE {table} (id INTEGER)")
    conn.executemany(f"INSERT INTO {table} VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    return conn


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _make_db(root / "apps/recorder/recorder.db", "ticks", 5).close()
    _make_db(root / "apps/hub/goals.db", "goals", 2).close()
    return root


@pytest.fixture
def data(tmp_path: Path):
    folder = tmp_path / "data"
    with patch("launcher.data_import.paths.data_dir", return_value=folder), patch("launcher.data_import.components.state", return_value=components.STOPPED), patch("launcher.data_import.components.find_processes", return_value=[]):
        yield folder


def _run(repo: Path, **kwargs) -> tuple[bool, list[str]]:
    said: list[str] = []
    return data_import.run(repo, said.append, **kwargs), said


def _rows(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_it_copies_the_records_and_goals_and_skips_a_missing_sync_db(repo: Path, data: Path) -> None:
    ok, said = _run(repo)
    assert ok
    assert _rows(data / "recorder.db", "ticks") == 5
    assert _rows(data / "goals.db", "goals") == 2
    assert not (data / "sync.db").exists()
    assert any("5개" in line for line in said)


def test_the_source_is_left_untouched(repo: Path, data: Path) -> None:
    before = (repo / "apps/recorder/recorder.db").read_bytes()
    _run(repo)
    assert (repo / "apps/recorder/recorder.db").read_bytes() == before


def test_changes_still_in_the_source_wal_are_copied(repo: Path, data: Path) -> None:
    source = repo / "apps/recorder/recorder.db"
    source.unlink()
    live = _make_db(source, "ticks", 3, wal=True)
    live.execute("INSERT INTO ticks VALUES (99)")
    live.commit()  # 아직 WAL에만 있다(연결이 열려 있어 합쳐지지 않았다)
    try:
        ok, _ = _run(repo)
    finally:
        live.close()
    assert ok
    assert _rows(data / "recorder.db", "ticks") == 4


def test_existing_data_is_not_overwritten_without_replace(repo: Path, data: Path) -> None:
    _make_db(data / "recorder.db", "ticks", 1).close()
    ok, said = _run(repo)
    assert not ok
    assert _rows(data / "recorder.db", "ticks") == 1
    assert not (data / "goals.db").exists()  # 아무것도 바꾸지 않았다
    assert any("--replace" in line for line in said)


def test_replace_keeps_the_previous_file_aside(repo: Path, data: Path) -> None:
    _make_db(data / "recorder.db", "ticks", 1).close()
    (data / "recorder.db-wal").write_bytes(b"stale")
    ok, _ = _run(repo, replace=True)
    assert ok
    assert _rows(data / "recorder.db", "ticks") == 5
    assert _rows(data / "recorder.db.before-import", "ticks") == 1
    assert not (data / "recorder.db-wal").exists()


def test_it_refuses_while_a_component_is_running(repo: Path, data: Path) -> None:
    with patch("launcher.data_import.components.state", return_value=components.SUPERVISED):
        ok, said = _run(repo)
    assert not ok
    assert not (data / "recorder.db").exists()
    assert any("stop" in line for line in said)


@pytest.mark.parametrize("module", ["hub", "desktop"])
def test_it_refuses_while_the_window_or_hub_is_running(repo: Path, data: Path, module: str) -> None:
    with patch("launcher.data_import.components.find_processes", side_effect=lambda name: ["process"] if name == module else []):
        ok, said = _run(repo, replace=True)
    assert not ok
    assert not (data / "recorder.db").exists()
    assert any("창" in line for line in said)


def _crashed_db(data: Path) -> None:
    """비정상 종료 뒤의 모습: 커밋된 행(2개)이 합쳐지지 않은 -wal에만 있는 recorder.db."""
    import shutil

    live = _make_db(data / "recorder.db", "ticks", 1, wal=True)
    live.execute("INSERT INTO ticks VALUES (7)")
    live.commit()
    snapshot = data.parent / "crashed"
    snapshot.mkdir()
    for suffix in ("", "-wal", "-shm"):
        shutil.copy(data / f"recorder.db{suffix}", snapshot / f"recorder.db{suffix}")
    live.close()
    for item in data.glob("recorder.db*"):
        item.unlink()
    for item in snapshot.iterdir():
        shutil.copy(item, data / item.name)
    assert (data / "recorder.db-wal").exists()


def test_replace_preserves_committed_changes_that_exist_only_in_the_old_wal(repo: Path, data: Path) -> None:
    _crashed_db(data)
    ok, _ = _run(repo, replace=True)
    assert ok
    assert _rows(data / "recorder.db", "ticks") == 5
    assert _rows(data / "recorder.db.before-import", "ticks") == 2  # WAL에만 있던 행까지


def test_a_failed_replace_keeps_the_existing_data_in_place(repo: Path, data: Path) -> None:
    _make_db(data / "recorder.db", "ticks", 1).close()
    (repo / "apps/recorder/recorder.db").write_bytes(b"not a database" * 100)
    ok, _ = _run(repo, replace=True)
    assert not ok
    assert _rows(data / "recorder.db", "ticks") == 1  # 새 복사본 검사가 먼저라 기존 것은 손대지 않았다
    assert not (data / "recorder.db.before-import").exists()


def test_a_failure_while_swapping_restores_the_previous_data(repo: Path, data: Path) -> None:
    _crashed_db(data)
    with patch("launcher.data_import.os.replace", side_effect=OSError("locked")):
        ok, _ = _run(repo, replace=True)
    assert not ok
    assert _rows(data / "recorder.db", "ticks") == 2  # WAL에만 있던 행도 잃지 않는다
    assert not list(data.glob("*.importing"))


def test_a_second_import_is_refused_while_one_is_running(repo: Path, data: Path) -> None:
    from supervision.lock import acquire_lock

    held = acquire_lock(data / "import.lock")
    try:
        ok, said = _run(repo)
    finally:
        held.release()
    assert not ok
    assert not (data / "recorder.db").exists()
    assert any("다른 가져오기" in line for line in said)
    ok, _ = _run(repo)  # 잠금을 놓으면 다시 할 수 있다
    assert ok


def test_dry_run_changes_nothing(repo: Path, data: Path) -> None:
    ok, said = _run(repo, dry_run=True)
    assert ok
    assert not data.exists()
    assert any("[미리보기]" in line for line in said)


def test_a_folder_without_databases_is_refused(tmp_path: Path, data: Path) -> None:
    ok, said = _run(tmp_path)
    assert not ok
    assert any("찾지 못했어요" in line for line in said)


def test_a_broken_source_leaves_no_partial_file(repo: Path, data: Path) -> None:
    (repo / "apps/recorder/recorder.db").write_bytes(b"not a database" * 100)
    ok, _ = _run(repo)
    assert not ok
    assert not (data / "recorder.db").exists()
    assert not list(data.glob("*.importing"))
    assert _rows(data / "goals.db", "goals") == 2  # 나머지는 계속 복사한다


def test_a_dev_checkout_is_refused(repo: Path) -> None:
    with patch("launcher.data_import.paths.data_dir", return_value=None):
        ok, said = _run(repo)
    assert not ok
    assert any("개발용 저장소" in line for line in said)
