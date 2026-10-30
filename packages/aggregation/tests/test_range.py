from datetime import UTC, datetime, timedelta, timezone

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


def test_splits_foreground_time_into_active_and_idle(tmp_path) -> None:
    """foreground였던 시간은 idle 여부에 따라 active와 idle로 나뉘어야 하고,
    둘이 섞이거나 겹치면 안 된다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "chrome.exe", {"chrome.exe"}, idle_seconds=0.0))
    save_tick(
        conn,
        _tick(
            now + timedelta(seconds=15),
            "chrome.exe",
            {"chrome.exe"},
            idle_seconds=100.0,  # IDLE_THRESHOLD_SECONDS(90)를 넘김
        ),
    )
    save_tick(conn, _tick(now + timedelta(seconds=30), "chrome.exe", {"chrome.exe"}))

    result = usage_by_range(conn, now, now + timedelta(seconds=31))

    row = result["by_process"][0]
    assert row["process"] == "chrome.exe"
    assert row["active_seconds"] == 15.0  # [0,15): idle=0 at t0 → active
    assert row["idle_seconds"] == 15.0  # [15,30): idle=100 at t15 → idle
    assert row["background_seconds"] == 0.0
    assert row["total_seconds"] == 30.0


def test_background_windows_accumulate_without_being_foreground(tmp_path) -> None:
    """동시에 떠 있던 여러 창은 각자 background_seconds를 중복으로 받아야
    한다 — 서로 다른 프로세스의 "열려 있던 시간"이라 겹치는 게 맞다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "code.exe", {"code.exe", "spotify.exe", "slack.exe"}))
    save_tick(conn, _tick(now + timedelta(seconds=15), "code.exe", {"code.exe"}))

    result = usage_by_range(conn, now, now + timedelta(seconds=16))

    by_process = {row["process"]: row for row in result["by_process"]}
    assert by_process["code.exe"]["active_seconds"] == 15.0
    assert by_process["code.exe"]["background_seconds"] == 0.0
    assert by_process["spotify.exe"]["active_seconds"] == 0.0
    assert by_process["spotify.exe"]["background_seconds"] == 15.0
    assert by_process["spotify.exe"]["total_seconds"] == 15.0
    assert by_process["slack.exe"]["background_seconds"] == 15.0


def test_foreground_is_counted_even_when_missing_from_windowed_set(tmp_path) -> None:
    """get_foreground_process_name()과 get_windowed_process_names()는 서로
    독립적으로 조회된다 — 제목 없는 foreground 창은 창 목록 필터에서 빠질 수
    있다. 이 경우에도 active/idle 집계에서 빠지면 안 된다."""
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
    """PC 절전이나 recorder 중단으로 생긴 긴 틱 간격은 어느 쪽에도 더해지면
    안 된다."""
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


def test_non_utc_bounds_select_the_same_ticks(tmp_path) -> None:
    """sampled_at은 UTC 문자열로 비교된다 — +09:00 같은 오프셋이 붙은 경계를
    넘겨도 같은 시각이면 같은 틱이 잡혀야 한다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    save_tick(conn, _tick(now, "code.exe", {"code.exe"}))
    save_tick(conn, _tick(now + timedelta(seconds=15), "code.exe", {"code.exe"}))
    save_tick(conn, _tick(now + timedelta(seconds=30), "code.exe", {"code.exe"}))

    kst = timezone(timedelta(hours=9))
    start, end = now - timedelta(seconds=1), now + timedelta(seconds=31)

    utc_result = usage_by_range(conn, start, end)
    kst_result = usage_by_range(conn, start.astimezone(kst), end.astimezone(kst))

    assert kst_result["by_process"] == utc_result["by_process"]
    assert kst_result["by_process"][0]["active_seconds"] == 30.0


def test_handles_no_ticks_in_range(tmp_path) -> None:
    """구간 안에 기록이 전혀 없으면 빈 결과를 돌려줘야 한다(에러가 아님)."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)

    result = usage_by_range(conn, now, now + timedelta(hours=24))

    assert result["by_process"] == []


def test_orders_by_total_then_active_descending(tmp_path) -> None:
    """전체 시간이 같으면 집중(active) 시간이 많은 프로세스가 먼저 와야 한다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    # a_idle: 15초 전부 idle, b_active: 15초 전부 active — 이름순이면 a_idle이 앞선다.
    save_tick(conn, _tick(now, "a_idle.exe", {"a_idle.exe"}, idle_seconds=100.0))
    save_tick(conn, _tick(now + timedelta(seconds=15), "b_active.exe", {"b_active.exe"}))
    save_tick(conn, _tick(now + timedelta(seconds=30), None, set()))
    # c_long: 더 오래 쓴 프로세스는 active가 0이어도 맨 앞.
    save_tick(conn, _tick(now + timedelta(seconds=40), "c_long.exe", {"c_long.exe"}, idle_seconds=100.0))
    save_tick(conn, _tick(now + timedelta(seconds=70), None, set()))

    result = usage_by_range(conn, now, now + timedelta(seconds=71))

    assert [row["process"] for row in result["by_process"]] == [
        "c_long.exe",
        "b_active.exe",
        "a_idle.exe",
    ]
