"""날짜별 달성 분 계산(`goalsync.daily`)은 목표의 기간 밖의 날을 올리지 않는다 — 기간 안의 날만 센다."""

from datetime import UTC, date, datetime, timedelta

from goals import GoalStore
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from goalsync.daily import day_entries

LOCAL = datetime.now().astimezone().tzinfo
DAY = date(2026, 11, 10)
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _record_chrome_on(path, day: date) -> None:
    """day의 낮 12시(로컬)부터 15초 간격으로 chrome.exe를 활성으로 21번 기록한다(5분 = 5달성 분 — 1분 미만이면 올릴 줄이 만들어지지 않아 시험이 아무것도 보지 못한다)."""
    conn = open_db(path)
    noon = datetime.combine(day, datetime.min.time(), tzinfo=LOCAL) + timedelta(hours=12)
    for offset in range(0, 21 * 15, 15):
        save_tick(
            conn,
            TickSample(
                sampled_at=(noon + timedelta(seconds=offset)).astimezone(UTC),
                foreground_process="chrome.exe",
                windowed_processes=frozenset({"chrome.exe"}),
                seconds_since_last_input=0.0,
            ),
        )
    conn.close()


def _store(tmp_path, **period):
    store = GoalStore(tmp_path / "goals.db")
    store.create(
        name="공부",
        daily_target_minutes=60,
        weekdays=ALL_DAYS,
        processes=["chrome.exe"],
        known_processes=["chrome.exe"],
        today=DAY - timedelta(days=10),
        **period,
    )
    return store


def test_time_recorded_outside_the_period_is_not_sent(tmp_path) -> None:
    recorder_db = tmp_path / "recorder.db"
    _record_chrome_on(recorder_db, DAY)
    with _store(tmp_path, start_date=(DAY + timedelta(days=3)).isoformat(), end_date=(DAY + timedelta(days=9)).isoformat()) as store:
        assert day_entries(store, recorder_db, [DAY]) == []  # 기록은 기간이 시작하기 전의 것이라 올리지 않는다


def test_time_recorded_inside_the_period_is_sent(tmp_path) -> None:
    recorder_db = tmp_path / "recorder.db"
    _record_chrome_on(recorder_db, DAY)
    with _store(tmp_path, start_date=(DAY - timedelta(days=1)).isoformat(), end_date=(DAY + timedelta(days=1)).isoformat()) as store:
        [entry] = day_entries(store, recorder_db, [DAY])
        assert (entry.day, entry.minutes, entry.target_minutes) == (DAY.isoformat(), 5, 60)


def test_a_goal_without_a_period_is_sent_for_every_day(tmp_path) -> None:
    recorder_db = tmp_path / "recorder.db"
    _record_chrome_on(recorder_db, DAY)
    with _store(tmp_path) as store:
        assert [entry.day for entry in day_entries(store, recorder_db, [DAY])] == [DAY.isoformat()]
