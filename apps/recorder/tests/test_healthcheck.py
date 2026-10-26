import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from recorder import healthcheck
from recorder.lock import AlreadyRunningError


def _make_db_with_last_tick(db_path, when: datetime) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE ticks (id INTEGER PRIMARY KEY, sampled_at TEXT NOT NULL)")
    conn.execute("INSERT INTO ticks (sampled_at) VALUES (?)", (when.isoformat(),))
    conn.commit()
    conn.close()


def test_unhealthy_when_not_running(tmp_path) -> None:
    """lock을 우리가 바로 잡을 수 있으면(AlreadyRunningError가 안 나면) 아무도 안 돌고 있다는 뜻이다."""
    db_path = tmp_path / "recorder.db"
    with patch("recorder.healthcheck.acquire_lock") as mock_acquire:
        mock_acquire.return_value = MagicMock()
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is False
    assert "실행 중이지 않습니다" in message


def test_unhealthy_when_running_but_no_db(tmp_path) -> None:
    db_path = tmp_path / "recorder.db"  # 아직 생성 안 됨
    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is False
    assert "DB 파일이 아직 없습니다" in message


def test_unhealthy_when_no_ticks_yet(tmp_path) -> None:
    db_path = tmp_path / "recorder.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE ticks (id INTEGER PRIMARY KEY, sampled_at TEXT NOT NULL)")
    conn.commit()
    conn.close()

    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is False
    assert "기록된 틱이 없습니다" in message


def test_healthy_when_last_tick_is_recent(tmp_path) -> None:
    db_path = tmp_path / "recorder.db"
    _make_db_with_last_tick(db_path, datetime.now(UTC) - timedelta(seconds=5))

    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is True
    assert "정상" in message


def test_unhealthy_when_last_tick_is_stale(tmp_path) -> None:
    """interval x STALE_MULTIPLIER(기본 3)보다 오래 조용하면 멈춘 것으로 본다."""
    db_path = tmp_path / "recorder.db"
    _make_db_with_last_tick(db_path, datetime.now(UTC) - timedelta(seconds=100))

    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is False
    assert "멈춘 것으로 보입니다" in message
