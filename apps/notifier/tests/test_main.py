from datetime import UTC, datetime, timedelta, timezone

import pytest
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from goals import GoalStore
from notifier import __main__ as notifier
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick
from supervision.lock import acquire_lock

KST = timezone(timedelta(hours=9))
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
NOON = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)  # KST 12:00 — 규칙을 만드는 시각


class _Clock:
    def __init__(self) -> None:
        self.now = NOON

    def __call__(self) -> datetime:
        return self.now


def _tick(conn, kst_hour, kst_minute, process, second=0):
    save_tick(
        conn,
        TickSample(
            sampled_at=datetime(2026, 11, 5, kst_hour, kst_minute, second, tzinfo=KST).astimezone(UTC),  # recorder는 UTC로 적는다
            foreground_process=process,
            windowed_processes=frozenset({process}),
            seconds_since_last_input=0.0,
        ),
    )


@pytest.fixture
def env(tmp_path):
    """recorder.db(KST 20:00~20:10에 game.exe를 활성으로 씀)와 목표 하나(game.exe 연결)가 든 goals.db."""
    recorder_db = tmp_path / "recorder.db"
    conn = open_db(recorder_db)
    for minute in range(0, 11):  # 15초 간격 틱(간격이 넓으면 집계가 한 틱의 길이를 잘라 낸다) — 10분 = 600초
        for second in (0, 15, 30, 45):
            if minute < 10 or second == 0:
                _tick(conn, 20, minute, "game.exe", second)
    conn.close()
    goals_db = tmp_path / "goals.db"
    with GoalStore(goals_db, now=_Clock()) as store:
        goal = store.create(
            name="출석",
            daily_target_minutes=10,
            weekdays=ALL_DAYS,
            processes=["game.exe"],
            known_processes=["game.exe"],
        )
    return goals_db, recorder_db, goal.id


def _alert(**overrides):
    fields = {"target_process": None, "deadline": "23:00", "min_minutes": 30, "weekdays": ALL_DAYS, "enabled": True}
    fields.update(overrides)
    return fields


def _add(goals_db, goal_id, **overrides):
    with GoalStore(goals_db, now=_Clock()) as store:
        return store.create_alert(goal_id, **_alert(**overrides))


class _Recorder:
    def __init__(self, result=True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.result = result

    def __call__(self, title, body) -> bool:
        self.calls.append((title, body))
        return self.result


def _check(env, hour, minute, notify):
    goals_db, recorder_db, _ = env
    return notifier.check_once(goals_db, recorder_db, now=datetime(2026, 11, 5, hour, minute, tzinfo=KST), notify=notify)


def test_an_unmet_alert_notifies_once_after_the_deadline(env) -> None:
    goals_db, _, goal_id = env
    _add(goals_db, goal_id)  # 목표 전체, 23:00까지 30분 — 실제로는 10분만 했다
    notify = _Recorder()

    assert _check(env, 22, 59, notify) == 0 and notify.calls == []  # 마감 전
    assert _check(env, 23, 0, notify) == 1
    assert _check(env, 23, 30, notify) == 0  # 오늘은 이미 알렸다
    [(title, body)] = notify.calls
    assert title == "whatever.log" and "'출석'" in body and "30분" in body and "지금 10분" in body


def test_a_met_alert_stays_silent(env) -> None:
    goals_db, _, goal_id = env
    _add(goals_db, goal_id, min_minutes=10)  # 10분은 채웠다
    notify = _Recorder()
    assert _check(env, 23, 30, notify) == 0 and notify.calls == []


def test_a_process_alert_names_the_process(env) -> None:
    goals_db, _, goal_id = env
    _add(goals_db, goal_id, target_process="GAME.exe", min_minutes=60)
    notify = _Recorder()
    assert _check(env, 23, 30, notify) == 1
    assert notify.calls[0][1].startswith("game.exe:")


def test_the_next_day_is_evaluated_again(env) -> None:
    goals_db, recorder_db, goal_id = env
    _add(goals_db, goal_id)
    notify = _Recorder()
    _check(env, 23, 30, notify)
    next_day = datetime(2026, 11, 6, 23, 30, tzinfo=KST)
    assert notifier.check_once(goals_db, recorder_db, now=next_day, notify=notify) == 1  # 어제 기록은 오늘 시간이 아니다
    assert len(notify.calls) == 2


def test_a_failed_toast_is_not_retried_the_same_day(env) -> None:
    goals_db, _, goal_id = env
    _add(goals_db, goal_id)
    broken = _Recorder(result=False)
    assert _check(env, 23, 30, broken) == 0 and len(broken.calls) == 1
    assert _check(env, 23, 40, broken) == 0 and len(broken.calls) == 1  # 알림이 반복되지 않는다


def test_disabled_alerts_do_not_even_open_the_recorder_db(tmp_path, env) -> None:
    goals_db, _, goal_id = env
    _add(goals_db, goal_id, enabled=False)
    notify = _Recorder()
    missing = tmp_path / "no-such-recorder.db"
    now = datetime(2026, 11, 5, 23, 30, tzinfo=KST)
    assert notifier.check_once(goals_db, missing, now=now, notify=notify) == 0


def test_an_unreadable_recorder_db_skips_the_check_without_marking(env, tmp_path) -> None:
    goals_db, _, goal_id = env
    _add(goals_db, goal_id)
    notify = _Recorder()
    now = datetime(2026, 11, 5, 23, 30, tzinfo=KST)
    assert notifier.check_once(goals_db, tmp_path / "missing.db", now=now, notify=notify) == 0
    assert notifier.check_once(goals_db, env[1], now=now, notify=notify) == 1  # 읽을 수 있게 되면 알린다


def test_the_agent_loops_and_survives_a_failure(env) -> None:
    goals_db, recorder_db, goal_id = env
    _add(goals_db, goal_id)
    clock = _Clock()
    clock.now = datetime(2026, 11, 5, 23, 30, tzinfo=KST)
    notify = _Recorder()
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise KeyboardInterrupt  # 계속 도는 루프를 끝낸다

    with pytest.raises(KeyboardInterrupt):
        notifier.main(
            ["--goals-db", str(goals_db), "--db-path", str(recorder_db), "--interval", "7", "--lock-path", str(goals_db.with_suffix(".lock")), "--log-path", str(goals_db.with_suffix(".log"))],
            sleep=sleep,
            notify=notify,
            clock=clock,
        )
    assert sleeps == [7.0, 7.0] and len(notify.calls) == 1


def test_once_runs_a_single_check(env) -> None:
    goals_db, recorder_db, goal_id = env
    _add(goals_db, goal_id)
    notify = _Recorder()
    clock = _Clock()
    clock.now = datetime(2026, 11, 5, 23, 30, tzinfo=KST)
    code = notifier.main(
        ["--once", "--goals-db", str(goals_db), "--db-path", str(recorder_db), "--lock-path", str(goals_db.with_suffix(".lock")), "--log-path", str(goals_db.with_suffix(".log"))],
        notify=notify,
        clock=clock,
    )
    assert code == 0 and len(notify.calls) == 1


def test_test_flag_shows_one_toast(tmp_path) -> None:
    notify = _Recorder()
    assert notifier.main(["--test", "--log-path", str(tmp_path / "n.log")], notify=notify) == 0
    assert len(notify.calls) == 1
    assert notifier.main(["--test", "--log-path", str(tmp_path / "n.log")], notify=_Recorder(result=False)) == 1


def test_a_second_agent_is_refused(env, tmp_path) -> None:
    goals_db, recorder_db, _ = env
    lock_path = tmp_path / "notifier.lock"
    held = acquire_lock(lock_path)
    try:
        code = notifier.main(
            ["--once", "--goals-db", str(goals_db), "--db-path", str(recorder_db), "--lock-path", str(lock_path), "--log-path", str(tmp_path / "n.log")],
            notify=_Recorder(),
        )
    finally:
        held.release()
    assert code == EXIT_ALREADY_RUNNING


@pytest.mark.parametrize("interval", ["abc", "1", "nan", "inf"])
def test_a_bad_interval_is_an_argument_error(interval, tmp_path) -> None:
    assert notifier.main(["--interval", interval, "--log-path", str(tmp_path / "n.log")]) == EXIT_ARGUMENT_ERROR


def test_a_rule_changed_while_being_evaluated_is_not_notified_with_the_old_values(env, monkeypatch) -> None:
    """평가하는 사이에 hub가 규칙을 끄거나 고치면, 낡은 판단으로 알리지도 오늘 기록을 남기지도 않는다(다음 확인에서 바뀐 규칙으로 다시 평가한다)."""
    goals_db, _, goal_id = env
    alert = _add(goals_db, goal_id)
    notify = _Recorder()
    real_due = notifier.due_alerts

    def due_then_hub_edits(*args, **kwargs):
        result = real_due(*args, **kwargs)
        with GoalStore(goals_db, now=_Clock()) as store:  # 평가가 끝난 뒤, 알리기 전에 사용자가 규칙을 끈다
            store.update_alert(alert.id, **_alert(enabled=False))
        return result

    monkeypatch.setattr(notifier, "due_alerts", due_then_hub_edits)
    assert _check(env, 23, 30, notify) == 0 and notify.calls == []
    with GoalStore(goals_db) as store:
        assert store.fired_alert_ids(datetime(2026, 11, 5, tzinfo=KST).date()) == set()
        store.update_alert(alert.id, **_alert(enabled=True))
    monkeypatch.setattr(notifier, "due_alerts", real_due)
    assert _check(env, 23, 31, notify) == 1  # 새 조건으로는 오늘 알림이 막히지 않았다


@pytest.mark.parametrize("argument", ["--inter", "--int=600", "--interv"])
def test_an_abbreviated_interval_is_an_argument_error(argument, tmp_path) -> None:
    """supervisor는 정확한 `--interval`만 읽는다 — 자식이 축약형을 받아들이면 둘이 주기를 다르게 읽어 박동 허용 시간이 어긋난다."""
    assert notifier.main([argument, "600", "--log-path", str(tmp_path / "n.log")]) == EXIT_ARGUMENT_ERROR
