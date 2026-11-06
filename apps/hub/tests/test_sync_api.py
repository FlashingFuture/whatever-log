import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import cloud
import keyring
import keyring.backend
import keyring.errors
import pytest
from cloud import GoalConflict, ProgressResult, RemoteGoal, ServerUnreachable
from goals import META_SYNC_ENABLED, GoalStore

from hub.__main__ import _Handler
from hub.account_service import AccountService, AccountUnavailable, SyncProblem
from hub.cloud_adapter import create_cloud_port

UI_ORIGIN = "http://127.0.0.1:5173"


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self.items.pop((service, username), None)


class FakeApi:
    """cloud.ServerApi 가짜(서버의 목표 목록을 메모리에 둔다)."""

    goals: dict[str, RemoteGoal] = {}
    fail: Exception | None = None
    created: list[tuple[str, str]] = []
    tokens: list[str] = []

    def __init__(self, url: str, token: str) -> None:
        FakeApi.tokens.append(token)

    def list_goals(self):
        if FakeApi.fail:
            raise FakeApi.fail
        return list(FakeApi.goals.values())

    def put_goal(self, goal_id, *, name, daily_target_minutes, weekdays, base_revision):
        if FakeApi.fail:
            raise FakeApi.fail
        if any(goal.name == name for goal in FakeApi.goals.values() if not goal.deleted):
            raise GoalConflict("duplicate_name", "같은 이름", None)
        goal = RemoteGoal(goal_id, False, 1, "t", name, daily_target_minutes, frozenset(weekdays))
        FakeApi.goals[goal_id] = goal
        FakeApi.created.append((goal_id, name))
        return goal

    def delete_goal(self, goal_id):
        return True

    def put_progress(self, device_id, entries):
        return ProgressResult(0, ())


@pytest.fixture
def sync_server(tmp_path, monkeypatch):
    """실제 어댑터(cloud·goalsync)에 가짜 ServerApi를 단 hub 서버와, 로그인한 세션."""
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    backend.set_password("whatever.log", "session", json.dumps({"token": "secret-token", "expires_at": None, "email": "a@example.com"}))
    FakeApi.goals, FakeApi.fail, FakeApi.created, FakeApi.tokens = {}, None, [], []
    monkeypatch.setattr(cloud, "ServerApi", FakeApi)

    goals_db = tmp_path / "goals.db"
    saved = (_Handler.account, _Handler.goals_db_path, _Handler.allowed_origins)
    _Handler.account = AccountService(create_cloud_port)
    _Handler.goals_db_path = goals_db
    _Handler.allowed_origins = frozenset({UI_ORIGIN})
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_port, goals_db, backend
    finally:
        server.shutdown()
        server.server_close()
        _Handler.account, _Handler.goals_db_path, _Handler.allowed_origins = saved
        keyring.set_keyring(previous)


def call(port, method, path, body=None, *, origin=UI_ORIGIN, host=None, content_type="application/json"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {}
    payload = None
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = content_type
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, (json.loads(raw) if raw else None)


def _local_goal(goals_db, name="공부", processes=("Code.exe",)):
    with GoalStore(goals_db) as store:
        return store.create(name=name, daily_target_minutes=120, weekdays=[0, 1, 2], processes=list(processes))


def test_the_plan_lists_what_would_go_out_and_never_the_process_links(sync_server) -> None:
    port, goals_db, _ = sync_server
    _local_goal(goals_db)
    FakeApi.goals["r-1"] = RemoteGoal("r-1", False, 3, "t", "독서", 30, frozenset({5, 6}))

    status, plan = call(port, "GET", "/api/sync/plan")

    assert status == 200 and plan["email"] == "a@example.com" and plan["enabled"] is False
    kinds = {item["kind"]: item for item in plan["items"]}
    assert kinds["upload"]["name"] == "공부" and kinds["upload"]["weekdays"] == [0, 1, 2]
    assert kinds["download"]["name"] == "독서"
    assert "Code.exe" not in json.dumps(plan) and "secret-token" not in json.dumps(plan)
    assert set(kinds["upload"]) == {
        "key", "kind", "name", "daily_target_minutes", "weekdays",
        "local_daily_target_minutes", "local_weekdays", "declined",
    }  # fmt: skip


def test_the_plan_uses_the_session_token_for_the_server(sync_server) -> None:
    port, _, _ = sync_server

    call(port, "GET", "/api/sync/plan")

    assert FakeApi.tokens == ["secret-token"]


def test_applying_only_what_the_user_checked(sync_server) -> None:
    port, goals_db, _ = sync_server
    keep = _local_goal(goals_db, "공부")
    other = _local_goal(goals_db, "운동", processes=("chrome.exe",))
    _, plan = call(port, "GET", "/api/sync/plan")
    upload_keys = {item["name"]: item["key"] for item in plan["items"]}

    status, result = call(port, "POST", "/api/sync/apply", {"accepted": [upload_keys["공부"]]})

    assert status == 200
    assert (result["uploaded"], result["kept_local"], result["errors"]) == (1, 1, [])
    assert [name for _, name in FakeApi.created] == ["공부"]  # 체크하지 않은 목표는 올라가지 않았다
    with GoalStore(goals_db) as store:
        links = {link.goal_id: link for link in store.sync_links()}
        assert links[keep.id].remote_id is not None and links[other.id].state == "local_only"
        assert store.get_meta(META_SYNC_ENABLED) == "1"
        assert store.get(keep.id).processes == ("Code.exe",)  # 프로세스 연결은 그대로


def test_downloading_a_server_goal_creates_it_here_without_process_links(sync_server) -> None:
    port, goals_db, _ = sync_server
    FakeApi.goals["r-1"] = RemoteGoal("r-1", False, 3, "t", "독서", 30, frozenset({5, 6}))
    _, plan = call(port, "GET", "/api/sync/plan")

    status, result = call(port, "POST", "/api/sync/apply", {"accepted": [plan["items"][0]["key"]]})

    assert status == 200 and result["downloaded"] == 1
    with GoalStore(goals_db) as store:
        (goal,) = store.list_goals()
        assert (goal.name, goal.processes, goal.sites) == ("독서", (), ())


def test_a_name_taken_after_the_plan_was_shown_becomes_a_merge_not_an_error(sync_server) -> None:
    port, goals_db, _ = sync_server
    _local_goal(goals_db, "공부")
    _, plan = call(port, "GET", "/api/sync/plan")
    FakeApi.goals["r-x"] = RemoteGoal("r-x", False, 1, "t", "공부", 10, frozenset({0}))  # 그 사이 다른 기기가 같은 이름을 만들었다

    status, result = call(port, "POST", "/api/sync/apply", {"accepted": [plan["items"][0]["key"]]})

    # 다시 읽은 계획에서는 같은 이름이라 합치기가 되므로 오류 없이 합쳐진다(두 기기가 같은 목표를 쓰게 된다).
    assert status == 200 and result["merged"] == 1 and result["errors"] == []


@pytest.mark.parametrize("failure", [ServerUnreachable(), cloud.ServerError(500, "internal_error", "서버 오류")])
def test_server_trouble_is_a_503_with_a_user_sentence(sync_server, failure) -> None:
    port, goals_db, _ = sync_server
    _local_goal(goals_db)
    FakeApi.fail = failure

    plan_status, plan_body = call(port, "GET", "/api/sync/plan")
    apply_status, apply_body = call(port, "POST", "/api/sync/apply", {"accepted": []})

    assert plan_status == apply_status == 503
    assert plan_body["error"]["code"] == "unavailable" and plan_body["error"]["message"]
    assert "secret-token" not in json.dumps([plan_body, apply_body])


def test_an_expired_token_asks_the_user_to_log_in_again(sync_server) -> None:
    port, _, _ = sync_server
    FakeApi.fail = cloud.NotAuthorized()

    status, body = call(port, "GET", "/api/sync/plan")

    assert status == 409 and "다시 로그인" in body["error"]["message"]


def test_signed_out_users_get_a_login_required_answer_and_nothing_is_sent(sync_server) -> None:
    port, goals_db, backend = sync_server
    backend.items.clear()
    _local_goal(goals_db)

    assert call(port, "GET", "/api/sync/plan")[0] == 409
    assert call(port, "POST", "/api/sync/apply", {"accepted": []})[0] == 409
    assert FakeApi.tokens == [] and FakeApi.created == []


@pytest.mark.parametrize(
    "body",
    [{}, {"accepted": "all"}, {"accepted": [1]}, {"accepted": [""]}, {"accepted": ["x" * 101]}, {"accepted": ["a"] * 101},
     {"accepted": [], "extra": 1}],
)  # fmt: skip
def test_invalid_apply_bodies_are_400(sync_server, body) -> None:
    port, goals_db, _ = sync_server
    _local_goal(goals_db)

    assert call(port, "POST", "/api/sync/apply", body)[0] == 400
    assert FakeApi.created == []


@pytest.mark.parametrize("origin", [None, "http://evil.example", "http://127.0.0.1:5174"])
def test_apply_needs_the_exact_ui_origin(sync_server, origin) -> None:
    port, goals_db, _ = sync_server
    _local_goal(goals_db)

    assert call(port, "POST", "/api/sync/apply", {"accepted": []}, origin=origin)[0] == 403
    assert FakeApi.created == []


def test_apply_rejects_a_foreign_host_and_a_non_json_body(sync_server) -> None:
    port, _, _ = sync_server

    assert call(port, "POST", "/api/sync/apply", {"accepted": []}, host="evil.example")[0] == 403
    assert call(port, "POST", "/api/sync/apply", {"accepted": []}, content_type="text/plain")[0] == 415


def test_reading_the_plan_from_a_foreign_host_is_refused(sync_server) -> None:
    port, _, _ = sync_server

    assert call(port, "GET", "/api/sync/plan", host="evil.example")[0] == 403


def test_without_cloud_the_sync_endpoints_answer_503_and_nothing_else_breaks(sync_server) -> None:
    port, _, _ = sync_server

    def broken():
        raise AccountUnavailable

    _Handler.account = AccountService(broken)

    assert call(port, "GET", "/api/sync/plan")[0] == 503
    assert call(port, "POST", "/api/sync/apply", {"accepted": []})[0] == 503
    assert call(port, "GET", "/api/goals")[0] == 200  # 목표 기능은 그대로


def test_a_second_apply_while_one_is_running_is_409() -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowPort:
        def providers(self):
            return ()

        def current(self):
            return None

        def sync_apply(self, goals_db, accepted):
            entered.set()
            release.wait(5)
            return {}

    service = AccountService(lambda: SlowPort())
    first = threading.Thread(target=lambda: service.sync_apply(None, []))
    first.start()
    assert entered.wait(2)

    from hub.account_service import SyncBusy

    with pytest.raises(SyncBusy):
        service.sync_apply(None, [])
    release.set()
    first.join()
    service.sync_apply(None, [])  # 끝난 뒤에는 다시 받는다


def test_sync_problem_carries_a_user_sentence() -> None:
    problem = SyncProblem("서버에 연결하지 못했습니다.", signed_out=False)

    assert problem.message == "서버에 연결하지 못했습니다." and problem.signed_out is False
