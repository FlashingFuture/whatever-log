import os
import sqlite3
import time
from contextlib import closing

import pytest

from chromium.snapshot import (
    create_work_dir,
    fingerprint,
    open_readonly,
    remove_stale_work_dirs,
    snapshot_database,
)


def _make_db(path, rows=("a",), wal=False) -> None:
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [(row,) for row in rows])
    conn.commit()
    conn.close()


def _values(path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT v FROM t")]
    finally:
        conn.close()


def test_snapshot_copies_a_database(tmp_path) -> None:
    _make_db(tmp_path / "src.db", ("a", "b"))

    assert snapshot_database(tmp_path / "src.db", tmp_path / "copy.db")

    assert _values(tmp_path / "copy.db") == ["a", "b"]


def test_paths_with_uri_special_characters_open_the_right_file(tmp_path) -> None:
    """"#"이나 "%41"이 든 폴더 이름이 file: URI에서 잘리거나 디코딩되면 다른 파일을 연다."""
    tricky = tmp_path / "profile#1 %41"
    tricky.mkdir()
    decoy = tmp_path / "profile#1 A"
    decoy.mkdir()
    _make_db(tricky / "src.db", ("right",))
    _make_db(decoy / "src.db", ("decoy",))

    assert snapshot_database(tricky / "src.db", tmp_path / "copy.db")
    assert _values(tmp_path / "copy.db") == ["right"]
    with closing(open_readonly(tricky / "src.db")) as db:
        assert [row[0] for row in db.execute("SELECT v FROM t")] == ["right"]
        with pytest.raises(sqlite3.OperationalError):  # 읽기 전용이다
            db.execute("INSERT INTO t VALUES ('x')")


def test_snapshot_includes_records_that_only_exist_in_the_wal(tmp_path) -> None:
    """WAL 모드에서 체크포인트 전의 기록은 -wal에만 있다 — 본 파일만 복사하면 빠진다."""
    source = tmp_path / "src.db"
    _make_db(source, ("old",), wal=True)
    reader = sqlite3.connect(source)  # 연결이 열려 있는 동안은 자동 체크포인트가 -wal을 비우지 않는다
    reader.execute("SELECT * FROM t").fetchall()
    writer = sqlite3.connect(source)
    writer.execute("INSERT INTO t VALUES ('new')")
    writer.commit()
    try:
        assert snapshot_database(source, tmp_path / "copy.db")
        assert sorted(_values(tmp_path / "copy.db")) == ["new", "old"]
    finally:
        writer.close()
        reader.close()


def test_snapshot_does_not_wait_forever_for_a_database_the_browser_keeps_locked(tmp_path) -> None:
    """브라우저가 쓰는 중인 프로필의 파일은 계속 잠겨 있다 — backup()은 풀릴 때까지 무한히 재시도해
    hub 요청과 recorder 틱 루프를 멈췄다. 기다리지 않고 파일 복사로 넘어가야 한다."""
    source = tmp_path / "src.db"
    _make_db(source, ("committed",))
    holder = sqlite3.connect(source, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")  # 다른 연결이 읽지 못하게 잠근다(브라우저의 배타적 잠금처럼)
    holder.execute("INSERT INTO t VALUES ('uncommitted')")
    try:
        started = time.monotonic()
        copied = snapshot_database(source, tmp_path / "copy.db")
        elapsed = time.monotonic() - started

        assert copied
        assert elapsed < 3, f"잠긴 파일에서 {elapsed:.1f}초 걸렸다(무한 재시도)"
        assert (tmp_path / "copy.db").exists()
    finally:
        holder.rollback()
        holder.close()


def test_snapshot_returns_false_and_leaves_nothing_for_a_missing_source(tmp_path) -> None:
    target = tmp_path / "copy.db"

    assert not snapshot_database(tmp_path / "missing.db", target)
    assert not target.exists()


def test_snapshot_falls_back_to_a_plain_copy_when_backup_fails(tmp_path) -> None:
    """SQLite 파일이 아니면 backup이 안 되지만, 파일 복사는 되므로 복사본은 만들어진다."""
    (tmp_path / "src.db").write_bytes(b"not a database")

    assert snapshot_database(tmp_path / "src.db", tmp_path / "copy.db")
    assert (tmp_path / "copy.db").read_bytes() == b"not a database"


def test_fingerprint_changes_when_the_wal_changes_and_is_none_for_a_missing_file(tmp_path) -> None:
    source = tmp_path / "src.db"
    assert fingerprint(source) is None

    source.write_bytes(b"main")
    without_wal = fingerprint(source)
    assert without_wal is not None and without_wal[1] is None

    (tmp_path / "src.db-wal").write_bytes(b"wal")
    with_wal = fingerprint(source)
    assert with_wal != without_wal and with_wal[1] is not None


def test_work_dir_name_contains_the_pid_and_a_sibling_process_is_left_alone(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    mine = create_work_dir("whatever-log-test-")
    assert mine.exists() and f"-{os.getpid()}-" in mine.name

    # 살아 있는 다른 프로세스(여기서는 부모)의 폴더는 지우지 않는다.
    alive_other = tmp_path / f"whatever-log-test-{os.getppid()}-abc"
    alive_other.mkdir()
    # 이미 없는 프로세스의 폴더, pid가 없는 옛 형식, 이 프로세스의 이전 실행분은 지운다.
    dead = tmp_path / "whatever-log-test-999999999-abc"
    legacy = tmp_path / "whatever-log-test-leftover"
    own_leftover = tmp_path / f"whatever-log-test-{os.getpid()}-old"
    unrelated = tmp_path / "something-else"
    for folder in (dead, legacy, own_leftover, unrelated):
        folder.mkdir()

    remove_stale_work_dirs("whatever-log-test-")

    assert alive_other.exists() and unrelated.exists()
    assert not dead.exists() and not legacy.exists() and not own_leftover.exists()
