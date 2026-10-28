from datetime import UTC, datetime, timedelta

from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from aggregation.today import today_usage


def _tick(sampled_at: datetime, foreground: str | None) -> TickSample:
    return TickSample(
        sampled_at=sampled_at,
        foreground_process=foreground,
        windowed_processes=frozenset({foreground} if foreground else set()),
        seconds_since_last_input=0.0,
    )


def test_aggregates_foreground_seconds_per_process(tmp_path) -> None:
    """각 구간은 그 구간이 시작될 때(앞쪽 틱) 관찰된 foreground 프로세스로
    집계된다 — 두 틱 사이에 정확히 언제 전환됐는지는 알 수 없어서, 앞쪽
    틱에서 관찰된 프로세스가 다음 틱까지 계속 foreground였다고 본다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "chrome.exe"))
    save_tick(conn, _tick(now + timedelta(seconds=15), "chrome.exe"))
    save_tick(conn, _tick(now + timedelta(seconds=30), "code.exe"))
    save_tick(conn, _tick(now + timedelta(seconds=45), "code.exe"))

    result = today_usage(conn, now=now)

    # [0,15)=chrome, [15,30)=chrome(15초 시점 관찰값), [30,45)=code.
    # 마지막 틱(45초)은 다음 구간이 없어 집계에서 빠진다.
    by_process = {row["process"]: row["seconds"] for row in result["by_process"]}
    assert by_process == {"chrome.exe": 30.0, "code.exe": 15.0}
    assert result["total_seconds"] == 45.0


def test_excludes_gaps_longer_than_threshold(tmp_path) -> None:
    """PC 절전이나 recorder 중단으로 생긴 긴 틱 간격은 그 시간 전부를
    마지막 foreground 프로세스 사용 시간으로 치면 안 된다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "chrome.exe"))
    save_tick(conn, _tick(now + timedelta(hours=2), "chrome.exe"))

    result = today_usage(conn, now=now)

    assert result["total_seconds"] == 0.0
    assert result["by_process"] == []


def test_only_includes_todays_local_date(tmp_path) -> None:
    """어제 기록된 틱은 오늘 집계에 포함되면 안 된다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    save_tick(conn, _tick(yesterday, "chrome.exe"))
    save_tick(conn, _tick(yesterday + timedelta(seconds=15), "chrome.exe"))
    save_tick(conn, _tick(now, "code.exe"))
    save_tick(conn, _tick(now + timedelta(seconds=15), "code.exe"))

    result = today_usage(conn, now=now)

    by_process = {row["process"]: row["seconds"] for row in result["by_process"]}
    assert by_process == {"code.exe": 15.0}


def test_handles_no_ticks_today(tmp_path) -> None:
    """오늘 기록이 전혀 없으면 빈 결과를 돌려줘야 한다(에러가 아님)."""
    conn = open_db(tmp_path / "recorder.db")

    result = today_usage(conn)

    assert result["total_seconds"] == 0.0
    assert result["by_process"] == []
