"""목표 기간의 동기화: 올리기·고치기·내려받기·확인 창(합치기·가져오기)에서 기간이 함께 오가고, 기간을 바꿔 목표에 들지 않게 된 날의
이미 보낸 달성 줄은 서버에서 지운다."""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from goals import META_ACCOUNT_EMAIL, META_SYNC_ENABLED
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from goalsync import KIND_DOWNLOAD, KIND_MERGE, apply_choices, build_plan, sync_once
from goalsync.plan import local_key, remote_key


def make_recorder_db(path: Path, ticks: dict[date, list[tuple[str, int]]]) -> Path:
    """로컬 날짜별로 (프로세스, 15초 틱 수)를 정오부터 이어 붙여 recorder.db를 만든다(test_runner와 같은 모양)."""
    conn = open_db(path)
    for day, runs in ticks.items():
        moment = datetime.combine(day, time(12, 0)).astimezone()
        for process, count in runs:
            for _ in range(count + 1):  # 마지막 틱은 집계에서 빠지므로 하나 더 둔다
                save_tick(
                    conn,
                    TickSample(
                        sampled_at=moment.astimezone(UTC),
                        foreground_process=process,
                        windowed_processes=frozenset({process}),
                        seconds_since_last_input=0.0,
                    ),
                )
                moment += timedelta(seconds=15)
    conn.close()
    return path

EMAIL = "a@example.com"
TODAY = date(2026, 11, 5)  # 목요일
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
START, END = "2026-11-10", "2026-11-30"


def _enable(store) -> None:
    store.set_meta(META_SYNC_ENABLED, "1")
    store.set_meta(META_ACCOUNT_EMAIL, EMAIL)


def _run(store, state, server, recorder_db):
    return sync_once(store, state, server, recorder_db, email=EMAIL, today=TODAY)


def _create(store, *, name="공부", start=None, end=None, processes=(), weekdays=ALL_DAYS):
    return store.create(
        name=name,
        daily_target_minutes=60,
        weekdays=weekdays,
        processes=list(processes),
        known_processes=list(processes),
        start_date=start,
        end_date=end,
        today=TODAY,
    )


def _update(store, goal, *, start=None, end=None, weekdays=None):
    return store.update(
        goal.id,
        name=goal.name,
        daily_target_minutes=goal.daily_target_minutes,
        weekdays=list(goal.weekdays if weekdays is None else weekdays),
        processes=list(goal.processes),
        known_processes=list(goal.processes),
        start_date=start,
        end_date=end,
        today=TODAY,
    )


def _linked(store, server, *, start=None, end=None, processes=(), weekdays=ALL_DAYS):
    goal = _create(store, start=start, end=end, processes=processes, weekdays=weekdays)
    remote = server.add("r-1", goal.name, minutes=60, weekdays=tuple(goal.weekdays), start_date=start, end_date=end)
    store.link_remote(goal.id, "r-1", remote.revision)
    return goal


def test_a_new_goal_is_uploaded_with_its_period(tmp_path, store, state, server) -> None:
    goal = _create(store, start=START, end=END)
    store.set_sync_state(goal.id, "sync")
    _enable(store)

    _run(store, state, server, tmp_path / "none.db")

    (remote,) = server.goals.values()
    assert (remote.start_date, remote.end_date) == (START, END)


def test_changing_only_the_period_marks_the_goal_dirty_and_pushes_it(tmp_path, store, state, server) -> None:
    goal = _linked(store, server)
    _enable(store)

    _update(store, goal, start=START, end=END)
    assert next(link for link in store.sync_links() if link.goal_id == goal.id).dirty

    _run(store, state, server, tmp_path / "none.db")

    assert (server.goals["r-1"].start_date, server.goals["r-1"].end_date) == (START, END)
    assert not next(link for link in store.sync_links() if link.goal_id == goal.id).dirty


def test_clearing_the_period_is_pushed_as_no_period(tmp_path, store, state, server) -> None:
    goal = _linked(store, server, start=START, end=END)
    _enable(store)

    _update(store, goal)
    _run(store, state, server, tmp_path / "none.db")

    assert (server.goals["r-1"].start_date, server.goals["r-1"].end_date) == (None, None)


def test_a_period_set_on_another_device_is_pulled_even_if_it_already_started(tmp_path, store, state, server) -> None:
    goal = _linked(store, server)
    _enable(store)
    # 다른 기기가 정한 기간은 이미 시작했을 수 있다 — "지난 날로는 정할 수 없다"는 이 PC가 고칠 때의 규칙이라 내려받기는 막지 않는다.
    server.edit("r-1", start_date="2026-10-01", end_date="2026-11-30")

    report = _run(store, state, server, tmp_path / "none.db")

    assert report.pulled == 1
    pulled = store.get(goal.id)
    assert (pulled.start_date, pulled.end_date) == (date(2026, 10, 1), date(2026, 11, 30))


def test_a_broken_period_from_the_server_is_reported_and_not_applied(tmp_path, store, state, server) -> None:
    goal = _linked(store, server)
    _enable(store)
    server.edit("r-1", start_date="2026-11-30", end_date="2026-11-01")

    report = _run(store, state, server, tmp_path / "none.db")

    assert report.pulled == 0 and report.problems
    assert store.get(goal.id).start_date is None


# --- 확인 창 ---


def test_a_merge_shows_both_periods_and_takes_the_servers(store, server) -> None:
    goal = _create(store, start=START, end=END)
    server.add("r-9", "공부", minutes=60, weekdays=tuple(ALL_DAYS))

    plan = build_plan(store, server.list_goals(), EMAIL)
    (item,) = plan.items
    assert item.kind == KIND_MERGE
    assert (item.start_date, item.end_date, item.local_start_date, item.local_end_date) == (None, None, START, END)

    apply_choices(store, server, plan, [local_key(goal.id)])
    assert store.get(goal.id).start_date is None  # 합치면 서버의 값(기간 없음)으로 맞춰진다


def test_a_download_brings_the_period(store, server) -> None:
    server.add("r-9", "독서", start_date=START, end_date=END)

    plan = build_plan(store, server.list_goals(), EMAIL)
    (item,) = plan.items
    assert (item.kind, item.start_date, item.end_date) == (KIND_DOWNLOAD, START, END)

    apply_choices(store, server, plan, [remote_key("r-9")])
    (goal,) = store.list_goals()
    assert (goal.start_date, goal.end_date) == (date(2026, 11, 10), date(2026, 11, 30))


def test_an_upload_from_the_plan_carries_the_period(store, server) -> None:
    goal = _create(store, start=START, end=END)

    plan = build_plan(store, server.list_goals(), EMAIL)
    apply_choices(store, server, plan, [local_key(goal.id)], new_id=lambda: "r-new")

    assert (server.goals["r-new"].start_date, server.goals["r-new"].end_date) == (START, END)


# --- 이미 보낸 달성 줄 정리 ---


def test_days_that_fall_outside_a_new_period_are_removed_from_the_server(tmp_path, store, state, server) -> None:
    earlier = TODAY - timedelta(days=2)
    db = make_recorder_db(tmp_path / "r.db", {earlier: [("Code.exe", 40)]})  # 10분
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, db)
    device = state.device_id()
    assert server.progress[("r-1", device, earlier.isoformat())] == (10, 60)
    server.progress[("r-1", "other-device", earlier.isoformat())] = (7, 60)  # 다른 기기의 줄

    # 오늘부터 시작하는 기간으로 바꾸면 이틀 전은 기간 밖이다
    _update(store, goal, start=TODAY.isoformat(), end=(TODAY + timedelta(days=10)).isoformat())
    report = _run(store, state, server, db)

    assert ("r-1", device, earlier.isoformat()) not in server.progress
    assert state.pushed("r-1", earlier.isoformat()) is None
    assert ("r-1", device, TODAY.isoformat()) in server.progress  # 기간 안의 날은 그대로
    assert server.progress[("r-1", "other-device", earlier.isoformat())] == (7, 60)  # 다른 기기의 줄은 그 기기가 정리한다
    assert report.progress_removed >= 1


def test_a_day_dropped_from_the_weekdays_is_removed_too(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {})
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, db)
    device = state.device_id()
    assert ("r-1", device, TODAY.isoformat()) in server.progress  # 목요일, 0분 줄

    _update(store, goal, weekdays=[0, 1, 2])  # 목요일을 뺀다(그날 시간도 없다)
    _run(store, state, server, db)

    assert ("r-1", device, TODAY.isoformat()) not in server.progress


def test_nothing_is_removed_when_every_sent_day_still_counts(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {TODAY: [("Code.exe", 40)]})
    _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, db)
    server.calls.clear()

    report = _run(store, state, server, db)

    assert report.progress_removed == 0 and "remove_progress" not in server.calls


def test_old_days_sent_at_first_link_are_removed_when_they_leave_the_period(tmp_path, store, state, server) -> None:
    old = TODAY - timedelta(days=20)  # 다시 계산하는 최근 8일보다 오래됐다(처음 연결 때 한 달치로 보냈다)
    db = make_recorder_db(tmp_path / "r.db", {old: [("Code.exe", 40)]})
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, db)
    device = state.device_id()
    assert ("r-1", device, old.isoformat()) in server.progress

    _update(store, goal, start=TODAY.isoformat(), end=(TODAY + timedelta(days=10)).isoformat())
    _run(store, state, server, db)

    assert ("r-1", device, old.isoformat()) not in server.progress
    assert state.pushed("r-1", old.isoformat()) is None


def test_old_days_still_inside_the_period_are_kept(tmp_path, store, state, server) -> None:
    old = TODAY - timedelta(days=20)
    db = make_recorder_db(tmp_path / "r.db", {old: [("Code.exe", 40)]})
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, db)

    # 요일만 바꿔 오래된 날의 요일이 빠져도 오래된 날은 다시 보지 않는다(지금 기간 밖일 때만 지운다).
    _update(store, goal, weekdays=[(old.weekday() + 1) % 7])
    _run(store, state, server, db)

    assert ("r-1", state.device_id(), old.isoformat()) in server.progress


def test_the_removed_count_is_what_the_server_actually_removed(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {})
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, db)
    device = state.device_id()
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    del server.progress[("r-1", device, yesterday)]  # 서버에는 이미 없다(다른 경로로 지워졌다)

    # 처음 연결 때 보낸 지난날(한 달치)이 모두 기간 밖이 된다 — 서버에 실제로 남아 있던 줄만 센다.
    on_server = [key for key in server.progress if key[1] == device and key[2] < TODAY.isoformat()]
    _update(store, goal, start=TODAY.isoformat(), end=(TODAY + timedelta(days=3)).isoformat())
    report = _run(store, state, server, db)

    assert report.progress_removed == len(on_server) > 0
    assert [key for key in server.progress if key[1] == device and key[2] < TODAY.isoformat()] == []
    assert state.pushed("r-1", yesterday) is None  # 서버에 없던 줄도 보낸 기록에서는 지운다
