from datetime import UTC, datetime, timedelta

from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from aggregation.range import usage_by_range


def _tick(
    sampled_at: datetime,
    foreground: str | None,
    windowed: set[str],
    *,
    idle_seconds: float = 0.0,
) -> TickSample:
    return TickSample(
        sampled_at=sampled_at,
        foreground_process=foreground,
        windowed_processes=frozenset(windowed),
        seconds_since_last_input=idle_seconds,
    )


def test_active_seconds_only_counts_non_idle_foreground_time(tmp_path) -> None:
    """foreground였어도 idle_threshold_seconds 이상 idle이었으면 active에서
    빠져야 하고, total에는(background 포함이라) 그대로 들어가야 한다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "chrome.exe", {"chrome.exe", "explorer.exe"}, idle_seconds=0.0))
    save_tick(
        conn,
        _tick(
            now + timedelta(seconds=15),
            "chrome.exe",
            {"chrome.exe", "explorer.exe"},
            idle_seconds=100.0,  # IDLE_THRESHOLD_SECONDS(90)를 넘김
        ),
    )
    save_tick(conn, _tick(now + timedelta(seconds=30), "code.exe", {"code.exe", "explorer.exe"}))

    result = usage_by_range(conn, now, now + timedelta(seconds=31))

    by_process = {row["process"]: row for row in result["by_process"]}
    assert by_process["chrome.exe"]["active_seconds"] == 15.0  # 첫 구간만
    assert by_process["chrome.exe"]["total_seconds"] == 30.0  # 두 구간 다
    assert by_process["explorer.exe"]["active_seconds"] == 0.0  # foreground였던 적 없음
    assert by_process["explorer.exe"]["total_seconds"] == 30.0  # 두 구간 다 떠 있었음
    assert "code.exe" not in by_process  # 마지막 틱이라 다음 구간이 없음


def test_background_windows_accumulate_total_without_being_foreground(tmp_path) -> None:
    """동시에 떠 있던 여러 창은 각자 total_seconds를 중복으로 받아야 한다 —
    서로 다른 프로세스의 "열려 있던 시간"이라 겹치는 게 맞다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "code.exe", {"code.exe", "spotify.exe", "slack.exe"}))
    save_tick(conn, _tick(now + timedelta(seconds=15), "code.exe", {"code.exe"}))

    result = usage_by_range(conn, now, now + timedelta(seconds=16))

    by_process = {row["process"]: row for row in result["by_process"]}
    assert by_process["code.exe"]["active_seconds"] == 15.0
    assert by_process["spotify.exe"]["active_seconds"] == 0.0
    assert by_process["spotify.exe"]["total_seconds"] == 15.0
    assert by_process["slack.exe"]["total_seconds"] == 15.0


def test_foreground_is_counted_in_total_even_when_missing_from_windowed_set(tmp_path) -> None:
    """get_foreground_process_name()과 get_windowed_process_names()는 서로
    독립적으로 조회된다 — 제목 없는 foreground 창은 창 목록 필터에서 빠질 수
    있다. 이 경우에도 active_seconds <= total_seconds가 보장되어야 한다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    # "ghost.exe"가 foreground지만 windowed_processes에는 없는 상황을 흉내낸다.
    save_tick(conn, _tick(now, "ghost.exe", set()))
    save_tick(conn, _tick(now + timedelta(seconds=15), "ghost.exe", set()))

    result = usage_by_range(conn, now, now + timedelta(seconds=16))

    by_process = {row["process"]: row for row in result["by_process"]}
    assert by_process["ghost.exe"]["active_seconds"] == 15.0
    assert by_process["ghost.exe"]["total_seconds"] == 15.0


def test_excludes_gaps_longer_than_threshold(tmp_path) -> None:
    """PC 절전이나 recorder 중단으로 생긴 긴 틱 간격은 active/total 어느 쪽에도
    더해지면 안 된다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "chrome.exe", {"chrome.exe"}))
    save_tick(conn, _tick(now + timedelta(hours=2), "chrome.exe", {"chrome.exe"}))

    result = usage_by_range(conn, now, now + timedelta(hours=2))

    assert result["by_process"] == []


def test_only_includes_ticks_within_the_requested_range(tmp_path) -> None:
    """요청 구간 밖의 틱은 집계에 들어가면 안 된다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    before_range = now - timedelta(hours=1)
    save_tick(conn, _tick(before_range, "chrome.exe", {"chrome.exe"}))
    save_tick(conn, _tick(before_range + timedelta(seconds=15), "chrome.exe", {"chrome.exe"}))
    save_tick(conn, _tick(now, "code.exe", {"code.exe"}))
    save_tick(conn, _tick(now + timedelta(seconds=15), "code.exe", {"code.exe"}))

    result = usage_by_range(conn, now, now + timedelta(hours=1))

    by_process = {row["process"]: row for row in result["by_process"]}
    assert "chrome.exe" not in by_process
    assert by_process["code.exe"]["active_seconds"] == 15.0


def test_handles_no_ticks_in_range(tmp_path) -> None:
    """구간 안에 기록이 전혀 없으면 빈 결과를 돌려줘야 한다(에러가 아님)."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)

    result = usage_by_range(conn, now, now + timedelta(hours=24))

    assert result["by_process"] == []
