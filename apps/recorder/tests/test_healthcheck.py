import argparse
import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

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
    """lock은 잡혀 있어도(실행 중) DB 파일이 아직 없으면 비정상으로 봐야 한다."""
    db_path = tmp_path / "recorder.db"  # 아직 생성 안 됨
    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is False
    assert "DB 파일이 아직 없습니다" in message


def test_unhealthy_when_db_exists_but_schema_is_not_ready_yet(tmp_path) -> None:
    """recorder가 lock은 잡았지만 open_db()로 테이블을 만들기 전인 아주 짧은
    순간에 체크하면 "no such table: ticks"(sqlite3.OperationalError)가 난다 —
    그대로 전파되면 안 되고 (False, 메시지)로 처리돼야 한다."""
    db_path = tmp_path / "recorder.db"
    sqlite3.connect(db_path).close()  # 파일만 있고 테이블은 없는 상태

    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is False
    assert "DB 스키마를 읽을 수 없습니다" in message


def test_unhealthy_when_no_ticks_yet(tmp_path) -> None:
    """DB는 있어도 ticks 테이블이 비어 있으면(막 시작한 직후 등) 비정상으로 봐야 한다."""
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
    """최근 틱이 기대 interval x STALE_MULTIPLIER 이내면 정상으로 봐야 한다."""
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


def test_unhealthy_when_last_tick_is_far_in_the_future(tmp_path) -> None:
    """시계가 뒤로 조정되면 마지막 틱이 "미래" 시각이 될 수 있다 — elapsed가 음수가
    돼서 그냥 두면 계속 정상으로 오판하므로 비정상으로 잡아야 한다."""
    db_path = tmp_path / "recorder.db"
    _make_db_with_last_tick(db_path, datetime.now(UTC) + timedelta(seconds=60))

    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is False
    assert "미래 시각" in message


def test_healthy_despite_tiny_clock_skew_into_the_future(tmp_path) -> None:
    """NTP 보정 등으로 생기는 아주 작은 시계 흔들림은 "미래 시각" 오판으로 잡으면 안 된다."""
    db_path = tmp_path / "recorder.db"
    _make_db_with_last_tick(db_path, datetime.now(UTC) + timedelta(seconds=1))

    with patch("recorder.healthcheck.acquire_lock", side_effect=AlreadyRunningError("x")):
        healthy, message = healthcheck.check(db_path, expected_interval=15.0)

    assert healthy is True
    assert "정상" in message


@pytest.mark.parametrize("bad_interval", [float("nan"), float("inf"), 0.0, -5.0])
def test_check_rejects_non_finite_or_non_positive_expected_interval(tmp_path, bad_interval) -> None:
    """nan/inf는 elapsed > threshold 비교를 항상 통과시켜 멈춘 recorder를 정상으로
    오판하게 하고, 0/음수는 반대로 정상인데도 비정상으로 오판하게 한다."""
    db_path = tmp_path / "recorder.db"

    with pytest.raises(ValueError, match="유한한 양수"):
        healthcheck.check(db_path, expected_interval=bad_interval)


@pytest.mark.parametrize("bad_interval", ["nan", "inf", "0", "-5"])
def test_cli_rejects_non_finite_or_non_positive_expected_interval(bad_interval) -> None:
    """CLI(argparse) 경로에서도 check()와 같은 조건으로 거부해야 한다."""
    with pytest.raises(argparse.ArgumentTypeError):
        healthcheck._expected_interval_type(bad_interval)
