import logging
from datetime import UTC, date, datetime

import pytest
import sync_agent.__main__ as agent
from cloud import (
    GoalConflict,
    InMemoryTokenStore,
    NotAuthorized,
    ProgressResult,
    RemoteGoal,
    ServerError,
    ServerUnreachable,
    Session,
)
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from goals import META_ACCOUNT_EMAIL, META_SYNC_ENABLED, GoalStore
from supervision.lock import acquire_lock

TODAY = date(2026, 11, 5)


class FakeApi:
    """서버 API 가짜: 모든 호출을 기록하고, fail이 있으면 그 예외를 올린다."""

    instances: list["FakeApi"] = []
    fail: Exception | None = None
    duplicate_name = False

    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url, token
        self.calls: list[str] = []
        FakeApi.instances.append(self)

    def _do(self, call: str):
        self.calls.append(call)
        if FakeApi.fail is not None:
            raise FakeApi.fail

    def list_goals(self) -> list[RemoteGoal]:
        self._do("list_goals")
        return []

    def put_goal(self, goal_id, *, name, daily_target_minutes, weekdays, base_revision):
        self._do("put_goal")
        if FakeApi.duplicate_name:
            raise GoalConflict("duplicate_name", f"'{name}'과 같은 이름의 목표가 있습니다.", None)
        return RemoteGoal(goal_id, False, 1, "t", name, daily_target_minutes, frozenset(weekdays))

    def delete_goal(self, goal_id) -> bool:
        self._do("delete_goal")
        return True

    def put_progress(self, device_id, entries) -> ProgressResult:
        self._do("put_progress")
        return ProgressResult(len(entries), ())


@pytest.fixture(autouse=True)
def _fake_server(monkeypatch):
    FakeApi.instances = []
    FakeApi.fail = None
    FakeApi.duplicate_name = False
    monkeypatch.setattr(agent, "ServerApi", FakeApi)
    monkeypatch.delenv("WHATEVER_LOG_SERVER_URL", raising=False)
    monkeypatch.delenv("WHATEVER_LOG_TOKEN", raising=False)


@pytest.fixture
def paths(tmp_path):
    return {
        "goals_db": tmp_path / "goals.db",
        "state_db": tmp_path / "sync.db",
        "recorder_db": tmp_path / "recorder.db",
        "server_url": "https://server.example",
    }


def _signed_in(email="a@example.com") -> InMemoryTokenStore:
    store = InMemoryTokenStore()
    store.save(Session("tok", None, email))
    return store


def _enable(goals_db, email="a@example.com") -> None:
    with GoalStore(goals_db) as goals:
        goals.set_meta(META_SYNC_ENABLED, "1")
        goals.set_meta(META_ACCOUNT_EMAIL, email)


def _cycle(token_store, paths, **overrides):
    return agent.run_cycle(token_store, today=lambda: TODAY, **{**paths, **overrides})


def test_a_signed_out_cycle_does_nothing_and_never_calls_the_server(paths) -> None:
    assert _cycle(InMemoryTokenStore(), paths) is None
    assert FakeApi.instances == []


def test_an_expired_login_counts_as_signed_out(paths) -> None:
    store = InMemoryTokenStore()
    store.save(Session("tok", datetime(2020, 1, 1, tzinfo=UTC), "a@example.com"))

    assert _cycle(store, paths) is None and FakeApi.instances == []


def test_before_the_user_confirms_sync_nothing_is_sent(paths) -> None:
    with GoalStore(paths["goals_db"]) as goals:
        goals.create(name="공부", daily_target_minutes=60, weekdays=[0], processes=[])

    report = _cycle(_signed_in(), paths)

    assert report.skipped == "not_enabled"
    assert all(not instance.calls for instance in FakeApi.instances)


def test_after_confirmation_goals_chosen_for_sync_are_uploaded_with_the_session_token(paths) -> None:
    with GoalStore(paths["goals_db"]) as goals:
        goal = goals.create(name="공부", daily_target_minutes=60, weekdays=[0], processes=["Code.exe"])
        goals.set_sync_state(goal.id, "sync")
    _enable(paths["goals_db"])

    report = _cycle(_signed_in(), paths)

    assert report.created == 1
    (api,) = FakeApi.instances
    assert (api.url, api.token) == ("https://server.example", "tok")
    assert "put_goal" in api.calls


def test_the_account_email_comes_from_the_session(paths) -> None:
    _enable(paths["goals_db"], email="old@example.com")

    report = _cycle(_signed_in("new@example.com"), paths)

    assert report.skipped == "account_changed"


# --- main(): 반복·종료 코드·로그 ---


def _args(tmp_path, *extra):
    return [
        "--goals-db", str(tmp_path / "goals.db"),
        "--db-path", str(tmp_path / "recorder.db"),
        "--state-db", str(tmp_path / "sync.db"),
        "--log-path", str(tmp_path / "sync.log"),
        "--token-from-env",
        *extra,
    ]  # fmt: skip


def test_once_without_a_token_exits_cleanly(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="sync_agent")

    assert agent.main(_args(tmp_path, "--once")) == 0
    assert "로그인되어 있지 않아 건너뜀" in caplog.text


def test_once_with_a_token_from_the_environment_syncs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    with GoalStore(tmp_path / "goals.db") as goals:
        goal = goals.create(name="공부", daily_target_minutes=60, weekdays=[0], processes=[])
        goals.set_sync_state(goal.id, "sync")
    _enable(tmp_path / "goals.db", email="a@example.com")
    monkeypatch.setattr(agent, "load_config", lambda: type("C", (), {"server_url": "http://127.0.0.1:1"})())

    # 환경 변수 토큰에는 이메일이 없어 계정을 확인할 수 없지만(None), 이미 켜져 있는 동기화는 그대로 돈다.
    assert agent.main(_args(tmp_path, "--once")) == 0
    assert FakeApi.instances and FakeApi.instances[0].token == "env-token"


@pytest.mark.parametrize(
    "error",
    [ServerUnreachable(), NotAuthorized(), ServerError(500, "internal_error", "서버 오류"), RuntimeError("boom")],
)
def test_once_reports_failure_with_exit_code_1_and_never_raises(tmp_path, monkeypatch, error) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    _enable(tmp_path / "goals.db")
    FakeApi.fail = error

    assert agent.main(_args(tmp_path, "--once")) == 1


def test_a_failing_cycle_does_not_stop_the_loop_and_backs_off_then_recovers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    _enable(tmp_path / "goals.db")
    sleeps: list[float] = []

    class Stop(Exception):
        pass

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            FakeApi.fail = None  # 서버가 돌아왔다
        if len(sleeps) == 5:
            raise Stop

    FakeApi.fail = ServerUnreachable()
    with pytest.raises(Stop):
        agent.main(_args(tmp_path, "--interval", "10"), sleep=fake_sleep)

    assert sleeps[:3] == [20, 40, 80]  # 연속 실패마다 두 배씩
    assert sleeps[3] == 10  # 한 번 성공하면 원래 주기로 돌아온다


def test_the_backoff_is_capped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    _enable(tmp_path / "goals.db")
    sleeps: list[float] = []

    class Stop(Exception):
        pass

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 12:
            raise Stop

    FakeApi.fail = ServerUnreachable()
    with pytest.raises(Stop):
        agent.main(_args(tmp_path, "--interval", "300"), sleep=fake_sleep)

    assert max(sleeps) == agent.MAX_BACKOFF_SECONDS


@pytest.mark.parametrize("value", ["abc", "nan", "inf", "-1", "1"])
def test_invalid_intervals_are_argument_errors(tmp_path, value) -> None:
    assert agent.main(_args(tmp_path, "--interval", value)) == EXIT_ARGUMENT_ERROR


def test_a_second_instance_is_refused(tmp_path) -> None:
    lock = acquire_lock((tmp_path / "sync.db").with_suffix(".lock"))
    try:
        assert agent.main(_args(tmp_path, "--once")) == EXIT_ALREADY_RUNNING
    finally:
        lock.release()


def test_a_database_from_a_newer_version_stops_the_agent(tmp_path, monkeypatch) -> None:
    import sqlite3

    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    raw = sqlite3.connect(tmp_path / "goals.db")
    raw.execute("PRAGMA user_version = 99")
    raw.close()

    assert agent.main(_args(tmp_path, "--interval", "10")) == 1  # 반복하지 않고 끝난다


def test_log_lines_never_contain_goal_names_or_the_token(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "super-secret-token")
    with GoalStore(tmp_path / "goals.db") as goals:
        goal = goals.create(name="비밀목표", daily_target_minutes=60, weekdays=[0], processes=["Secret.exe"])
        goals.set_sync_state(goal.id, "sync")
    _enable(tmp_path / "goals.db")
    caplog.set_level(logging.DEBUG, logger="sync_agent")

    agent.main(_args(tmp_path, "--once"))

    assert "비밀목표" not in caplog.text and "Secret.exe" not in caplog.text and "super-secret-token" not in caplog.text
    assert "올림 1" in caplog.text


def test_a_name_clash_with_the_server_is_logged_as_a_count_never_with_the_goal_name(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    with GoalStore(tmp_path / "goals.db") as goals:
        goal = goals.create(name="비밀목표", daily_target_minutes=60, weekdays=[0], processes=[])
        goals.set_sync_state(goal.id, "sync")
    _enable(tmp_path / "goals.db")
    FakeApi.duplicate_name = True
    caplog.set_level(logging.DEBUG, logger="sync_agent")

    assert agent.main(_args(tmp_path, "--once")) == 0

    assert "비밀목표" not in caplog.text  # 서버의 오류 문장·문제 문장 어디에도 이름이 새지 않는다
    assert "문제 1건" in caplog.text
    assert "비밀목표" not in (tmp_path / "sync.log").read_text(encoding="utf-8")


# --- 화면이 읽을 동기화 상태 ---


def _status(goals_db):
    from goals.sync_status import read_record

    with GoalStore(goals_db) as store:
        return read_record(store)


def test_each_cycle_records_its_result_for_the_screen(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)

    assert agent.main(_args(tmp_path, "--once", "--interval", "60")) == 0

    record = _status(goals_db)
    assert (record.result, record.problems, record.interval) == ("ok", 0, 60.0)
    assert record.last_success_at == record.at


def test_a_cycle_that_cannot_reach_the_server_records_the_kind_and_keeps_the_last_success(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)
    agent.main(_args(tmp_path, "--once"))
    first = _status(goals_db)

    FakeApi.fail = ServerUnreachable()
    assert agent.main(_args(tmp_path, "--once")) == 1

    record = _status(goals_db)
    assert record.result == "unreachable" and record.last_success_at == first.last_success_at


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (NotAuthorized(), "not_authorized"),
        (ServerError(500, "internal_error", "서버 오류"), "server_error"),
        (RuntimeError("boom"), "internal"),
    ],
)
def test_other_failures_are_recorded_by_kind(tmp_path, monkeypatch, error, kind) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)
    FakeApi.fail = error

    agent.main(_args(tmp_path, "--once"))

    assert _status(goals_db).result == kind


def test_a_signed_out_or_not_enabled_cycle_is_recorded_as_a_skip_not_an_error(tmp_path, monkeypatch) -> None:
    goals_db = tmp_path / "goals.db"
    agent.main(_args(tmp_path, "--once"))  # 토큰 없음
    assert _status(goals_db).result == "signed_out"

    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    agent.main(_args(tmp_path, "--once"))  # 로그인했지만 동기화를 켜지 않음
    assert _status(goals_db).result == "not_enabled"


def test_the_recorded_status_never_contains_names_or_tokens(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "super-secret-token")
    goals_db = tmp_path / "goals.db"
    with GoalStore(goals_db) as goals:
        goal = goals.create(name="비밀목표", daily_target_minutes=60, weekdays=[0], processes=["Secret.exe"])
        goals.set_sync_state(goal.id, "sync")
    _enable(goals_db)
    FakeApi.duplicate_name = True

    agent.main(_args(tmp_path, "--once"))

    with GoalStore(goals_db) as store:
        raw = store.get_meta("sync_status")
    assert raw is not None and "비밀목표" not in raw and "Secret.exe" not in raw and "super-secret-token" not in raw
    assert _status(goals_db).problems == 1  # 건수만 남는다


def test_a_status_that_cannot_be_written_does_not_stop_the_sync(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    with GoalStore(goals_db) as goals:
        goal = goals.create(name="공부", daily_target_minutes=60, weekdays=[0], processes=[])
        goals.set_sync_state(goal.id, "sync")
    _enable(goals_db)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(agent.status, "record", broken)

    assert agent.main(_args(tmp_path, "--once")) == 0
    assert "put_goal" in FakeApi.instances[0].calls  # 상태는 못 적었어도 동기화는 됐다


# --- 리뷰: 백오프 반영, 낡은 주기의 상태, 기기 ID 알림 ---


def test_the_recorded_interval_is_the_real_backoff_so_a_waiting_agent_is_not_called_stopped(tmp_path, monkeypatch) -> None:
    from datetime import timedelta

    from goals import sync_status

    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)
    FakeApi.fail = ServerUnreachable()
    sleeps: list[float] = []

    class Stop(Exception):
        pass

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise Stop

    with pytest.raises(Stop):
        agent.main(_args(tmp_path, "--interval", "300"), sleep=fake_sleep)

    record = _status(goals_db)
    assert sleeps == [600, 1200]  # 두 번 연속 실패하면 1200초를 기다린다
    assert record.interval == 1200  # 상태에도 실제로 기다리는 시간이 적혀 있다
    # 1000초가 지나도(옛 기준 900초를 넘었다) 에이전트는 멈춘 것이 아니라 기다리는 중이다.
    now = datetime.fromisoformat(record.at) + timedelta(seconds=1000)
    assert sync_status.describe(record, enabled=True, now=now)["state"] == "error"


def test_next_delay_grows_by_failures_and_is_capped() -> None:
    assert agent.next_delay(300, 0) == 300
    assert [agent.next_delay(300, n) for n in (1, 2, 3)] == [600, 1200, 2400]
    assert agent.next_delay(300, 6) == agent.MAX_BACKOFF_SECONDS == agent.next_delay(300, 50)


def test_a_status_from_a_cycle_whose_account_was_cleared_meanwhile_is_not_recorded(tmp_path, monkeypatch) -> None:
    from goals import StaleSyncError

    goals_db = tmp_path / "goals.db"
    with GoalStore(goals_db) as store:
        old_generation = store.generation()
        store.reset_sync()

    agent.record_status(goals_db, result="ok", problems=0, interval=300, expect_generation=old_generation)

    assert _status(goals_db) is None  # 이전 계정 주기의 "성공"이 새 계정의 상태로 남지 않았다
    assert StaleSyncError  # (예외는 삼켜지고 에이전트는 계속 돈다)


def test_the_cycle_hands_its_generation_to_the_status_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)
    seen: list[int | None] = []
    original = agent.record_status
    monkeypatch.setattr(agent, "record_status", lambda *a, **k: (seen.append(k.get("expect_generation")), original(*a, **k))[1])

    agent.main(_args(tmp_path, "--once"))

    assert seen == [0]  # 켠 뒤 첫 주기의 세대


def test_the_agent_publishes_this_pcs_device_id_into_the_shared_goals_db(tmp_path, monkeypatch) -> None:
    from goals import META_DEVICE_ID

    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)

    agent.main(_args(tmp_path, "--once"))

    from goalsync import peek_device_id

    with GoalStore(goals_db) as store:
        published = store.get_meta(META_DEVICE_ID)
    assert published is not None and published == peek_device_id(tmp_path / "sync.db")


# --- 리뷰 3: 실패한 주기·낡은 주기의 상태, 기기 ID를 먼저 알림 ---


class _ResetsWhileFailing(FakeApi):
    """서버 요청이 실패하는 순간, 다른 프로세스(화면)가 계정을 정리한 상황을 흉내 낸다."""

    goals_db = None

    def list_goals(self):
        with GoalStore(type(self).goals_db) as store:
            store.reset_sync()
        raise ServerUnreachable


def test_a_failure_from_a_cycle_whose_account_was_cleared_meanwhile_is_not_recorded(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)
    _ResetsWhileFailing.goals_db = goals_db
    monkeypatch.setattr(agent, "ServerApi", _ResetsWhileFailing)

    assert agent.main(_args(tmp_path, "--once")) == 1

    # 이전 계정 주기의 "서버에 닿지 못함"이 정리된 DB의 상태로 남아, 새 계정에서 동기화를 켰을 때 낡은 오류로 보이지 않는다.
    assert _status(goals_db) is None


def test_the_device_id_is_published_before_the_cycle_can_send_anything(tmp_path, monkeypatch) -> None:
    from goals import META_DEVICE_ID

    monkeypatch.setenv("WHATEVER_LOG_TOKEN", "env-token")
    goals_db = tmp_path / "goals.db"
    _enable(goals_db)
    seen: list[str | None] = []

    class Spy(FakeApi):
        def list_goals(self):
            with GoalStore(goals_db) as store:
                seen.append(store.get_meta(META_DEVICE_ID))  # 주기가 서버를 부르는 시점에 이미 알려져 있는가
            return super().list_goals()

    monkeypatch.setattr(agent, "ServerApi", Spy)

    agent.main(_args(tmp_path, "--once"))

    assert seen and seen[0] is not None


def test_status_is_not_recorded_when_the_generation_could_not_be_read(tmp_path) -> None:
    from goals.sync_status import read_record

    goals_db = tmp_path / "goals.db"
    with GoalStore(goals_db):
        pass

    agent.record_status(goals_db, result="ok", problems=0, interval=300, expect_generation=None)

    with GoalStore(goals_db) as store:
        assert read_record(store) is None
