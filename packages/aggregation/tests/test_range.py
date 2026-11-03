from datetime import UTC, datetime, timedelta, timezone

from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

import pytest

from aggregation.range import (
    process_usage_by_bucket,
    site_usage_by_range,
    usage_by_range,
)


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


def test_orders_by_active_then_total_descending(tmp_path) -> None:
    """집중(active) 시간이 많은 프로세스가 먼저, 같으면 전체 시간이 긴 쪽이 먼저 와야 한다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    # a_idle: 15초 전부 idle, b_active: 15초 전부 active — 이름순이면 a_idle이 앞선다.
    # 전체 시간만 보면 c_long(30초)이 맨 앞이지만 active가 0이라 b_active 뒤로 간다.
    save_tick(conn, _tick(now, "a_idle.exe", {"a_idle.exe"}, idle_seconds=100.0))
    save_tick(conn, _tick(now + timedelta(seconds=15), "b_active.exe", {"b_active.exe"}))
    save_tick(conn, _tick(now + timedelta(seconds=30), None, set()))
    # c_long: active는 0이지만 a_idle보다 오래 떠 있다 — active 동률(0)에서는 전체 시간순.
    save_tick(conn, _tick(now + timedelta(seconds=40), "c_long.exe", {"c_long.exe"}, idle_seconds=100.0))
    save_tick(conn, _tick(now + timedelta(seconds=70), None, set()))

    result = usage_by_range(conn, now, now + timedelta(seconds=71))

    assert [row["process"] for row in result["by_process"]] == [
        "b_active.exe",
        "c_long.exe",
        "a_idle.exe",
    ]


def test_float_noise_does_not_break_active_ties(tmp_path) -> None:
    """같은 간격들을 서로 다른 순서로 쓴 두 프로세스는 집중 시간이 이론상 같다. 더하는
    순서 때문에 생기는 1e-13 단위 오차가 동률 판정(이름순)을 깨면 안 된다."""
    conn = open_db(tmp_path / "recorder.db")
    now = datetime.now(UTC)
    # 불규칙한 간격(0.1초 단위)이라 float 합이 순서에 따라 어긋난다.
    gaps = [0.1, 0.7, 0.3, 0.9, 0.2, 0.6, 0.4, 0.8, 0.5, 1.1] * 3
    t = now
    # z_first는 gaps 순서대로, a_second는 거꾸로 — 이름순이면 a_second가 먼저여야 한다.
    for name, order in (("z_first.exe", gaps), ("a_second.exe", gaps[::-1])):
        for gap in order:
            save_tick(conn, _tick(t, name, {name}))
            t += timedelta(seconds=gap)
    save_tick(conn, _tick(t, None, set()))

    result = usage_by_range(conn, now, t + timedelta(seconds=1))

    assert [row["process"] for row in result["by_process"]] == [
        "a_second.exe",
        "z_first.exe",
    ]


def test_process_usage_by_bucket_splits_one_process_by_edges(tmp_path) -> None:
    """칸마다 그 칸에 시작한 구간만 들어가고, 다른 프로세스는 섞이지 않는다."""
    conn = open_db(tmp_path / "recorder.db")
    base = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    # 칸0 [0:00,1:00): chrome foreground 2틱(30초) + code가 foreground일 때 background 15초.
    # 칸1 [1:00,2:00): chrome idle 15초.
    save_tick(conn, _tick(base, "chrome.exe", {"chrome.exe", "code.exe"}))
    save_tick(conn, _tick(base + timedelta(seconds=15), "chrome.exe", {"chrome.exe"}))
    save_tick(conn, _tick(base + timedelta(seconds=30), "code.exe", {"chrome.exe", "code.exe"}))
    save_tick(conn, _tick(base + timedelta(seconds=45), None, set()))  # 칸0의 마지막 구간을 닫는다
    save_tick(
        conn,
        _tick(base + timedelta(hours=1), "chrome.exe", {"chrome.exe"}, idle_seconds=100.0),
    )
    save_tick(conn, _tick(base + timedelta(hours=1, seconds=15), None, set()))

    series = process_usage_by_bucket(
        conn, "chrome.exe", [base, base + timedelta(hours=1), base + timedelta(hours=2)]
    )

    assert series["process"] == "chrome.exe"
    first, second = series["buckets"]
    assert first["active_seconds"] == 30.0
    assert first["background_seconds"] == 15.0
    assert first["total_seconds"] == 45.0
    assert second["idle_seconds"] == 15.0
    assert second["active_seconds"] == 0.0


def test_process_usage_by_bucket_matches_usage_by_range_totals(tmp_path) -> None:
    """칸을 모두 더하면 같은 구간의 전체 집계와 같아야 한다(분류 규칙이 같은 코드라는 보증)."""
    conn = open_db(tmp_path / "recorder.db")
    base = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    for i in range(40):
        save_tick(
            conn,
            _tick(
                base + timedelta(seconds=15 * i),
                "chrome.exe" if i % 3 else "code.exe",
                {"chrome.exe", "code.exe"},
                idle_seconds=100.0 if i % 5 == 0 else 0.0,
            ),
        )
    end = base + timedelta(minutes=11)
    edges = [base + timedelta(minutes=m) for m in (0, 3, 7, 11)]

    series = process_usage_by_bucket(conn, "chrome.exe", edges)
    whole = {r["process"]: r for r in usage_by_range(conn, base, end)["by_process"]}["chrome.exe"]

    for field in ("active_seconds", "idle_seconds", "background_seconds"):
        assert sum(b[field] for b in series["buckets"]) == pytest.approx(whole[field])


def test_process_usage_by_bucket_fills_empty_buckets_and_validates_edges(tmp_path) -> None:
    conn = open_db(tmp_path / "recorder.db")
    base = datetime(2026, 10, 28, 0, 0, tzinfo=UTC)

    series = process_usage_by_bucket(conn, "none.exe", [base, base + timedelta(hours=1)])
    assert [b["total_seconds"] for b in series["buckets"]] == [0.0]

    with pytest.raises(ValueError):
        process_usage_by_bucket(conn, "none.exe", [base])
    with pytest.raises(ValueError):
        process_usage_by_bucket(conn, "none.exe", [base + timedelta(hours=1), base])


def _site_tick(
    sampled_at: datetime, site: str | None, *, idle_seconds: float = 0.0
) -> TickSample:
    return TickSample(
        sampled_at=sampled_at,
        foreground_process="chrome.exe",
        windowed_processes=frozenset({"chrome.exe"}),
        seconds_since_last_input=idle_seconds,
        foreground_site=site,
    )


def test_site_usage_splits_active_and_idle_per_domain(tmp_path) -> None:
    """사이트별로 active/idle이 나뉘고, 사이트를 모르는 틱의 시간은 어느 사이트에도 안 들어간다."""
    conn = open_db(tmp_path / "recorder.db")
    t0 = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
    ticks = [
        (0, "a.example.com", 0.0),
        (15, "a.example.com", 100.0),  # idle
        (30, None, 0.0),  # 사이트를 못 찾은 구간
        (45, "b.example.com", 0.0),
        (60, "b.example.com", 0.0),
        (75, None, 0.0),  # 마지막 구간을 닫는 틱
    ]
    for offset, site, idle in ticks:
        save_tick(conn, _site_tick(t0 + timedelta(seconds=offset), site, idle_seconds=idle))

    result = site_usage_by_range(conn, t0, t0 + timedelta(minutes=5))

    assert result["by_site"] == [
        {
            "domain": "b.example.com",
            "active_seconds": 30.0,
            "idle_seconds": 0.0,
            "total_seconds": 30.0,
        },
        {
            "domain": "a.example.com",
            "active_seconds": 15.0,
            "idle_seconds": 15.0,
            "total_seconds": 30.0,
        },
    ]


def test_site_usage_skips_long_gaps_and_other_ranges(tmp_path) -> None:
    """절전으로 보이는 긴 간격과 구간 밖의 틱은 세지 않는다."""
    conn = open_db(tmp_path / "recorder.db")
    t0 = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
    save_tick(conn, _site_tick(t0, "a.example.com"))
    save_tick(conn, _site_tick(t0 + timedelta(seconds=15), "a.example.com"))
    save_tick(conn, _site_tick(t0 + timedelta(minutes=10), "a.example.com"))  # 10분 공백
    save_tick(conn, _site_tick(t0 + timedelta(hours=5), "z.example.com"))
    save_tick(conn, _site_tick(t0 + timedelta(hours=5, seconds=15), None))

    result = site_usage_by_range(conn, t0, t0 + timedelta(hours=1))

    assert [row["domain"] for row in result["by_site"]] == ["a.example.com"]
    assert result["by_site"][0]["total_seconds"] == 15.0


def test_site_usage_orders_by_active_then_total_then_name(tmp_path) -> None:
    conn = open_db(tmp_path / "recorder.db")
    t0 = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
    # idle만 길게 쓴 사이트는 active가 있는 사이트 뒤로 가고, 완전히 같으면 이름순이다.
    rows = [
        ("c.example.com", 100.0, 3),  # idle 45초
        ("b.example.com", 0.0, 1),  # active 15초
        ("a.example.com", 0.0, 1),  # active 15초(동률)
    ]
    t = t0
    for domain, idle, count in rows:
        for _ in range(count + 1):
            save_tick(conn, _site_tick(t, domain, idle_seconds=idle))
            t += timedelta(seconds=15)
    save_tick(conn, _site_tick(t, None))

    result = site_usage_by_range(conn, t0, t + timedelta(minutes=1))

    assert [row["domain"] for row in result["by_site"]] == [
        "a.example.com",
        "b.example.com",
        "c.example.com",
    ]
