import logging
from datetime import UTC, date, datetime

import pytest
import sync_agent.__main__ as agent
from cloud import (
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
