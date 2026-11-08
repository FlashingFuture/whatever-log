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
EMAIL = "a@example.com"


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.fail_delete = False

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if self.fail_delete:
            raise keyring.errors.PasswordDeleteError("잠금")
        self.items.pop((service, username), None)


class FakeApi:
    """cloud.ServerApi 가짜(서버의 목표 목록을 메모리에 둔다)."""

    goals: dict[str, RemoteGoal] = {}
    fail: Exception | None = None
    created: list[tuple[str, str]] = []
    tokens: list[str] = []
    calls: list[str] = []

    def __init__(self, url: str, token: str) -> None:
        FakeApi.tokens.append(token)

    def list_goals(self):
        FakeApi.calls.append("list_goals")
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

    devices: list = []
    deleted_devices: list[str] = []
    account_deleted = False

    def list_devices(self):
        FakeApi.calls.append("list_devices")
        if FakeApi.fail:
            raise FakeApi.fail
        return list(FakeApi.devices)

    def delete_device(self, device_id):
        FakeApi.calls.append("delete_device")
        if FakeApi.fail:
            raise FakeApi.fail
        FakeApi.deleted_devices.append(device_id)

    def delete_account(self):
        FakeApi.calls.append("delete_account")
        if FakeApi.fail:
            raise FakeApi.fail
        FakeApi.account_deleted = True

    def put_progress(self, device_id, entries):
        return ProgressResult(0, ())


@pytest.fixture
def sync_server(tmp_path, monkeypatch):
    """실제 어댑터(cloud·goalsync)에 가짜 ServerApi를 단 hub 서버와, 로그인한 세션."""
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    backend.set_password("whatever.log", "session", json.dumps({"token": "secret-token", "expires_at": None, "email": "a@example.com"}))
    FakeApi.goals, FakeApi.fail, FakeApi.created, FakeApi.tokens, FakeApi.calls = {}, None, [], [], []
    FakeApi.devices, FakeApi.deleted_devices, FakeApi.account_deleted = [], [], False
    monkeypatch.setattr(cloud, "ServerApi", FakeApi)

    goals_db = tmp_path / "goals.db"
    saved = (_Handler.account, _Handler.goals_db_path, _Handler.allowed_origins, _Handler.sync_db_path)
    _Handler.sync_db_path = tmp_path / "sync.db"
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
        _Handler.account, _Handler.goals_db_path, _Handler.allowed_origins, _Handler.sync_db_path = saved
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

    status, result = call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": [upload_keys["공부"]]})

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

    status, result = call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": [plan["items"][0]["key"]]})

    assert status == 200 and result["downloaded"] == 1
    with GoalStore(goals_db) as store:
        (goal,) = store.list_goals()
        assert (goal.name, goal.processes, goal.sites) == ("독서", (), ())


def test_a_name_taken_after_the_plan_was_shown_becomes_a_merge_not_an_error(sync_server) -> None:
    port, goals_db, _ = sync_server
    _local_goal(goals_db, "공부")
    _, plan = call(port, "GET", "/api/sync/plan")
    FakeApi.goals["r-x"] = RemoteGoal("r-x", False, 1, "t", "공부", 10, frozenset({0}))  # 그 사이 다른 기기가 같은 이름을 만들었다

    status, result = call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": [plan["items"][0]["key"]]})

    # 다시 읽은 계획에서는 같은 이름이라 합치기가 되므로 오류 없이 합쳐진다(두 기기가 같은 목표를 쓰게 된다).
    assert status == 200 and result["merged"] == 1 and result["errors"] == []


@pytest.mark.parametrize("failure", [ServerUnreachable(), cloud.ServerError(500, "internal_error", "서버 오류")])
def test_server_trouble_is_a_503_with_a_user_sentence(sync_server, failure) -> None:
    port, goals_db, _ = sync_server
    _local_goal(goals_db)
    FakeApi.fail = failure

    plan_status, plan_body = call(port, "GET", "/api/sync/plan")
    apply_status, apply_body = call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": []})

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
    assert call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": []})[0] == 409
    assert FakeApi.tokens == [] and FakeApi.created == []


@pytest.mark.parametrize(
    "body",
    [{}, {"email": "a@example.com", "accepted": "all"}, {"email": "a@example.com", "accepted": [1]}, {"email": "a@example.com", "accepted": [""]}, {"email": "a@example.com", "accepted": ["x" * 101]}, {"email": "a@example.com", "accepted": ["a"] * 101},
     {"email": "a@example.com", "accepted": [], "extra": 1}, {"accepted": []}, {"email": 5, "accepted": []},
     {"email": "x" * 321, "accepted": []}],
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

    assert call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": []}, origin=origin)[0] == 403
    assert FakeApi.created == []


def test_apply_rejects_a_foreign_host_and_a_non_json_body(sync_server) -> None:
    port, _, _ = sync_server

    assert call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": []}, host="evil.example")[0] == 403
    assert call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": []}, content_type="text/plain")[0] == 415


def test_reading_the_plan_from_a_foreign_host_is_refused(sync_server) -> None:
    port, _, _ = sync_server

    assert call(port, "GET", "/api/sync/plan", host="evil.example")[0] == 403


def test_without_cloud_the_sync_endpoints_answer_503_and_nothing_else_breaks(sync_server) -> None:
    port, _, _ = sync_server

    def broken():
        raise AccountUnavailable

    _Handler.account = AccountService(broken)

    assert call(port, "GET", "/api/sync/plan")[0] == 503
    assert call(port, "POST", "/api/sync/apply", {"email": "a@example.com", "accepted": []})[0] == 503
    assert call(port, "GET", "/api/goals")[0] == 200  # 목표 기능은 그대로


def test_a_second_apply_while_one_is_running_is_409() -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowPort:
        def providers(self):
            return ()

        def current(self):
            return None

        def sync_apply(self, goals_db, accepted, email):
            entered.set()
            release.wait(5)
            return {}

    service = AccountService(lambda: SlowPort())
    first = threading.Thread(target=lambda: service.sync_apply(None, [], None))
    first.start()
    assert entered.wait(2)

    from hub.account_service import SyncBusy

    with pytest.raises(SyncBusy):
        service.sync_apply(None, [], None)
    release.set()
    first.join()
    service.sync_apply(None, [], None)  # 끝난 뒤에는 다시 받는다


def test_sync_problem_carries_a_user_sentence() -> None:
    problem = SyncProblem("서버에 연결하지 못했습니다.", signed_out=False)

    assert problem.message == "서버에 연결하지 못했습니다." and problem.signed_out is False


def test_a_plan_confirmed_for_one_account_is_never_applied_to_another(sync_server) -> None:
    port, goals_db, backend = sync_server
    _local_goal(goals_db)
    _, plan = call(port, "GET", "/api/sync/plan")
    key = plan["items"][0]["key"]
    # 확인 창을 연 사이에 다른 계정으로 로그인했다
    backend.set_password(
        "whatever.log", "session", json.dumps({"token": "tok-b", "expires_at": None, "email": "b@example.com"})
    )

    status, body = call(port, "POST", "/api/sync/apply", {"email": plan["email"], "accepted": [key]})

    assert status == 503 and "계정이 바뀌었어요" in body["error"]["message"]
    assert FakeApi.created == [] and FakeApi.calls == ["list_goals"]  # 계획 때의 한 번뿐 — 적용 때는 서버를 부르지 않았다
    with GoalStore(goals_db) as store:
        assert store.get_meta(META_SYNC_ENABLED) is None  # 아무것도 켜지지 않았다


def test_a_token_the_server_rejects_is_forgotten_so_the_login_button_shows(sync_server) -> None:
    port, _, backend = sync_server
    FakeApi.fail = cloud.NotAuthorized()

    status, _ = call(port, "GET", "/api/sync/plan")

    assert status == 409
    assert backend.items == {}  # 이 PC의 로그인 정보가 지워졌다
    assert call(port, "GET", "/api/account")[1]["signed_in"] is False


def test_a_bad_server_address_is_a_clear_message_not_a_crash(sync_server, monkeypatch) -> None:
    port, _, _ = sync_server
    monkeypatch.setenv("WHATEVER_LOG_SERVER_URL", "ftp://nope")

    status, body = call(port, "GET", "/api/sync/plan")

    assert status == 503 and "서버 주소" in body["error"]["message"]


# --- 동기화 상태 / 기기 목록 / 계정 삭제 ---

DEVICE_A = "00000000-0000-4000-8000-00000000000a"
DEVICE_B = "00000000-0000-4000-8000-00000000000b"


def _record(goals_db, **kwargs):
    from goals import sync_status

    with GoalStore(goals_db) as store:
        return sync_status.record(store, **kwargs)


def test_the_sync_status_is_off_until_the_user_turns_sync_on(sync_server) -> None:
    port, goals_db, _ = sync_server

    status, body = call(port, "GET", "/api/sync/status")

    assert status == 200 and body["enabled"] is False and body["state"] == "off"


def test_the_sync_status_reports_waiting_ok_error_and_a_silent_agent(sync_server) -> None:
    from datetime import UTC, datetime, timedelta

    port, goals_db, _ = sync_server
    with GoalStore(goals_db) as store:
        store.set_meta(META_SYNC_ENABLED, "1")
    assert call(port, "GET", "/api/sync/status")[1]["state"] == "waiting"

    now = datetime.now(UTC)
    _record(goals_db, result="ok", problems=0, interval=300, now=now)
    ok = call(port, "GET", "/api/sync/status")[1]
    assert ok["state"] == "ok" and ok["last_success_at"] == ok["last_attempt_at"]

    _record(goals_db, result="unreachable", problems=0, interval=300, now=now)
    failed = call(port, "GET", "/api/sync/status")[1]
    assert (failed["state"], failed["result"]) == ("error", "unreachable") and failed["last_success_at"]

    _record(goals_db, result="ok", problems=0, interval=300, now=now - timedelta(hours=2))
    assert call(port, "GET", "/api/sync/status")[1]["state"] == "stale"


def test_the_sync_status_needs_no_login_and_never_calls_the_server(sync_server) -> None:
    port, goals_db, backend = sync_server
    backend.items.clear()

    assert call(port, "GET", "/api/sync/status")[0] == 200
    assert FakeApi.calls == [] and FakeApi.tokens == []


def test_the_sync_status_has_only_counts_kinds_and_times(sync_server) -> None:
    port, goals_db, _ = sync_server
    with GoalStore(goals_db) as store:
        store.set_meta(META_SYNC_ENABLED, "1")
    _record(goals_db, result="ok", problems=2, interval=300)

    body = call(port, "GET", "/api/sync/status")[1]

    assert set(body) == {"enabled", "state", "result", "last_attempt_at", "last_success_at", "problems"}


def test_the_sync_status_is_readable_even_without_the_account_feature(sync_server) -> None:
    port, _, _ = sync_server

    def broken():
        raise AccountUnavailable

    _Handler.account = AccountService(broken)

    assert call(port, "GET", "/api/sync/status")[0] == 200


def test_the_device_list_marks_this_pc_by_the_agents_device_id(sync_server, tmp_path) -> None:
    from cloud import DeviceInfo
    from goalsync import SyncState

    port, _, _ = sync_server
    with SyncState(tmp_path / "sync.db") as state:
        mine = state.device_id()
    FakeApi.devices = [DeviceInfo(DEVICE_A, "2026-11-06T03:00:00.000Z", 3), DeviceInfo(mine, "2026-11-07T03:00:00.000Z", 9)]

    status, body = call(port, "GET", "/api/devices")

    assert status == 200
    assert [(d["device_id"], d["is_this_device"]) for d in body["devices"]] == [(DEVICE_A, False), (mine, True)]
    assert set(body["devices"][0]) == {"device_id", "last_sent_at", "rows", "is_this_device"}  # 이름 같은 칸이 없다


def test_no_device_is_marked_as_this_pc_before_the_agent_has_ever_run(sync_server) -> None:
    from cloud import DeviceInfo

    port, _, _ = sync_server
    FakeApi.devices = [DeviceInfo(DEVICE_A, "t", 1)]

    assert call(port, "GET", "/api/devices")[1]["devices"][0]["is_this_device"] is False


def test_a_device_can_be_deleted_but_not_this_pcs_own(sync_server, tmp_path) -> None:
    from goalsync import SyncState

    port, _, _ = sync_server
    with SyncState(tmp_path / "sync.db") as state:
        mine = state.device_id()

    assert call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}")[0] == 204
    refused = call(port, "DELETE", f"/api/devices/{mine}?email={EMAIL}")

    assert FakeApi.deleted_devices == [DEVICE_A]
    assert refused[0] == 503 and "이 기기" in refused[1]["error"]["message"]


@pytest.mark.parametrize("path", ["/api/devices/not-a-uuid", "/api/devices/", "/api/devices/00000000-0000-4000-8000-00000000000a/x"])
def test_malformed_device_paths_are_404(sync_server, path) -> None:
    port, _, _ = sync_server

    assert call(port, "DELETE", path + f"?email={EMAIL}")[0] == 404
    assert FakeApi.deleted_devices == []


def test_device_deletion_needs_the_exact_origin_and_no_body(sync_server) -> None:
    port, _, _ = sync_server

    assert call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}", origin="http://evil.example")[0] == 403
    assert call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}", origin=None)[0] == 403
    assert call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}", {"x": 1})[0] == 400
    assert FakeApi.deleted_devices == []


def test_device_endpoints_report_server_trouble_and_expired_logins(sync_server) -> None:
    port, _, backend = sync_server
    FakeApi.fail = ServerUnreachable()
    assert call(port, "GET", "/api/devices")[0] == 503
    assert call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}")[0] == 503

    FakeApi.fail = cloud.NotAuthorized()
    assert call(port, "GET", "/api/devices")[0] == 409
    assert backend.items == {}  # 거부된 토큰은 지워진다


def _delete_account(port, email=EMAIL, **kwargs):
    return call(port, "POST", "/api/account/delete", {"email": email}, **kwargs)


def test_deleting_the_account_removes_the_server_data_then_cleans_this_pc(sync_server) -> None:
    port, goals_db, backend = sync_server
    goal = _local_goal(goals_db)
    with GoalStore(goals_db) as store:
        store.link_remote(goal.id, "r-1", 2)
        store.set_meta(META_SYNC_ENABLED, "1")
        store.set_meta("account_email", EMAIL)

    status, body = _delete_account(port)

    assert status == 200 and FakeApi.account_deleted is True
    assert (body["deleted_on_server"], body["signed_out"], body["connections_cleared"]) == (True, True, True)
    assert body["signed_in"] is False and backend.items == {}  # 로그인 정보가 지워졌다
    with GoalStore(goals_db) as store:
        link = store.sync_links()[0]
        assert (link.remote_id, link.state) == (None, "ask")  # 서버 연결은 끊겼지만
        assert store.get(goal.id).processes == ("Code.exe",)  # 목표와 프로세스 연결은 이 PC에 그대로 있다
        assert store.get_meta(META_SYNC_ENABLED) is None


def _linked_and_enabled(goals_db):
    goal = _local_goal(goals_db)
    with GoalStore(goals_db) as store:
        store.link_remote(goal.id, "r-1", 2)
        store.set_meta(META_SYNC_ENABLED, "1")


def test_when_the_server_refuses_to_delete_this_pc_is_left_exactly_as_it_was(sync_server) -> None:
    port, goals_db, backend = sync_server
    _linked_and_enabled(goals_db)
    FakeApi.fail = cloud.ServerError(500, "internal_error", "서버 오류")

    status, body = _delete_account(port)

    assert status == 503 and body["error"]["message"]  # 서버가 거부했다 — 지워지지 않았다고 말할 수 있다
    assert backend.items != {}  # 계정은 남아 있으니 로그인 정보도 그대로다(지울 방법을 잃지 않는다)
    with GoalStore(goals_db) as store:
        assert store.sync_links()[0].remote_id == "r-1" and store.get_meta(META_SYNC_ENABLED) == "1"


def test_when_the_answer_is_lost_the_outcome_is_reported_as_unknown_and_this_pc_is_left_alone(sync_server) -> None:
    port, goals_db, backend = sync_server
    _linked_and_enabled(goals_db)
    FakeApi.fail = ServerUnreachable()  # 요청은 보냈지만 응답을 받지 못했다 — 서버가 이미 지웠을 수 있다

    status, body = _delete_account(port)

    assert status == 504  # "연결하지 못했다"가 아니라 "결과를 알 수 없다"
    assert "지워졌는지 확인하지 못했어요" in body["error"]["message"] and "로그아웃되어 있으면" in body["error"]["message"]
    assert backend.items != {}  # 단정할 수 없으니 이 PC는 그대로 둔다
    with GoalStore(goals_db) as store:
        assert store.sync_links()[0].remote_id == "r-1"


def test_after_a_lost_answer_the_next_server_call_notices_the_deleted_account(sync_server) -> None:
    port, goals_db, backend = sync_server
    FakeApi.fail = ServerUnreachable()
    assert _delete_account(port)[0] == 504

    FakeApi.fail = cloud.NotAuthorized()  # 서버는 정말로 지웠다 — 이제 토큰이 거부된다
    status, _ = call(port, "GET", "/api/sync/plan")

    assert status == 409 and backend.items == {}  # 그때 이 PC의 로그인 정보가 정리되어 로그인 버튼이 보인다


def test_a_failure_to_read_the_account_after_the_server_deleted_is_still_a_success(sync_server, monkeypatch) -> None:
    port, goals_db, _ = sync_server
    original = _Handler.account.snapshot
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        raise OSError("keyring exploded") if calls["n"] >= 1 else None

    monkeypatch.setattr(_Handler.account, "snapshot", flaky)

    status, body = _delete_account(port)

    assert status == 200 and body["deleted_on_server"] is True  # 이미 지워진 계정에 503을 보내지 않는다
    assert body["signed_in"] is False and original is not None


def test_an_account_confirmed_for_someone_else_is_never_deleted(sync_server) -> None:
    port, _, backend = sync_server

    status, body = _delete_account(port, email="someone-else@example.com")

    assert status == 503 and "계정이 바뀌었어요" in body["error"]["message"]
    assert FakeApi.account_deleted is False and backend.items != {}


@pytest.mark.parametrize("body", [{}, {"email": 5}, {"email": "a@example.com", "extra": 1}, {"email": "x" * 321}])
def test_invalid_delete_account_bodies_are_400(sync_server, body) -> None:
    port, _, _ = sync_server

    assert call(port, "POST", "/api/account/delete", body)[0] == 400
    assert FakeApi.account_deleted is False


def test_deleting_the_account_needs_the_exact_origin_json_and_a_login(sync_server) -> None:
    port, _, backend = sync_server

    assert _delete_account(port, origin="http://evil.example")[0] == 403
    assert _delete_account(port, origin=None)[0] == 403
    assert _delete_account(port, host="evil.example")[0] == 403
    assert call(port, "POST", "/api/account/delete", {"email": EMAIL}, content_type="text/plain")[0] == 415
    assert FakeApi.account_deleted is False

    backend.items.clear()
    assert _delete_account(port)[0] == 409  # 로그인 전
    assert FakeApi.account_deleted is False


def test_an_expired_token_during_account_deletion_clears_the_login_and_says_so(sync_server) -> None:
    port, _, backend = sync_server
    FakeApi.fail = cloud.NotAuthorized()

    status, _ = _delete_account(port)

    assert status == 409 and backend.items == {}


def test_a_failed_local_cleanup_after_the_server_deleted_is_reported_not_hidden(sync_server) -> None:
    port, goals_db, backend = sync_server
    backend.fail_delete = True

    status, body = _delete_account(port)

    assert status == 200 and FakeApi.account_deleted is True
    assert body["deleted_on_server"] is True and body["signed_out"] is False  # 서버에서는 지워졌지만 이 PC는 로그아웃하지 못했다


def test_deleting_the_account_cancels_a_login_in_progress(sync_server) -> None:
    port, _, _ = sync_server
    cancelled: list[bool] = []
    original = _Handler.account.cancel_login
    _Handler.account.cancel_login = lambda: (cancelled.append(True), original())[1]

    _delete_account(port)

    assert cancelled == [True]


# --- 리뷰: 기기 목록과 계정, 이 기기 확인, 삭제 중 로그인 ---


def test_the_device_list_says_which_account_it_belongs_to(sync_server) -> None:
    port, _, _ = sync_server

    assert call(port, "GET", "/api/devices")[1]["email"] == EMAIL


def test_a_device_confirmed_in_one_accounts_list_is_never_deleted_from_another_account(sync_server) -> None:
    port, goals_db, backend = sync_server
    backend.set_password("whatever.log", "session", json.dumps({"token": "tok-b", "expires_at": None, "email": "b@example.com"}))

    status, body = call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}")  # 계정 A의 목록에서 누른 삭제

    assert status == 503 and "계정이 바뀌었어요" in body["error"]["message"]
    assert FakeApi.deleted_devices == []


@pytest.mark.parametrize("query", ["", "?other=1", "?email=a@example.com&email=b@example.com", "?email=a@example.com&x=1", "?email=" + "x" * 321])
def test_the_device_delete_needs_exactly_one_email(sync_server, query) -> None:
    port, _, _ = sync_server

    assert call(port, "DELETE", f"/api/devices/{DEVICE_A}{query}")[0] == 400
    assert FakeApi.deleted_devices == []


def test_this_pc_is_recognized_through_the_shared_goals_db_even_if_the_sync_db_path_differs(sync_server) -> None:
    from cloud import DeviceInfo

    port, goals_db, _ = sync_server
    with GoalStore(goals_db) as store:
        store.set_meta("device_id", DEVICE_B)  # 에이전트가 goals.db에 알린 이 PC의 기기 ID(sync.db는 hub가 보는 위치에 없다)
    FakeApi.devices = [DeviceInfo(DEVICE_B, "t", 1), DeviceInfo(DEVICE_A, "t", 1)]

    devices = call(port, "GET", "/api/devices")[1]["devices"]
    refused = call(port, "DELETE", f"/api/devices/{DEVICE_B}?email={EMAIL}")

    assert {d["device_id"]: d["is_this_device"] for d in devices} == {DEVICE_B: True, DEVICE_A: False}
    assert refused[0] == 503 and "이 기기" in refused[1]["error"]["message"]
    assert FakeApi.deleted_devices == []


def test_when_sync_is_on_but_this_pc_cannot_be_identified_nothing_is_deleted(sync_server) -> None:
    port, goals_db, _ = sync_server
    with GoalStore(goals_db) as store:
        store.set_meta(META_SYNC_ENABLED, "1")  # 켰는데 에이전트가 기기 ID를 아직 알리지 않았다

    status, body = call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}")

    assert status == 503 and "확인하지 못했어요" in body["error"]["message"] and "에이전트" in body["error"]["message"]
    assert FakeApi.deleted_devices == []


def test_when_sync_is_off_other_devices_can_be_deleted_without_knowing_this_pcs_id(sync_server) -> None:
    port, _, _ = sync_server

    assert call(port, "DELETE", f"/api/devices/{DEVICE_A}?email={EMAIL}")[0] == 204
    assert FakeApi.deleted_devices == [DEVICE_A]


def test_logging_in_is_refused_while_the_account_is_being_deleted(sync_server) -> None:
    import threading as _threading

    port, _, _ = sync_server
    inside = _threading.Event()
    release = _threading.Event()
    original = FakeApi.delete_account

    def slow(self):
        inside.set()
        assert release.wait(5)
        return original(self)

    FakeApi.delete_account = slow
    try:
        worker = _threading.Thread(target=lambda: _delete_account(port))
        worker.start()
        assert inside.wait(5)

        status, body = call(port, "POST", "/api/account/login", {"provider": "google"})

        assert status == 409 and "지우는 중" in body["error"]["message"]
        release.set()
        worker.join()
        assert call(port, "POST", "/api/account/login", {"provider": "google"})[0] in (202, 503)  # 끝난 뒤에는 다시 받는다
    finally:
        FakeApi.delete_account = original
        release.set()


def test_the_account_reset_after_deletion_raises_the_sync_generation(sync_server) -> None:
    port, goals_db, _ = sync_server
    with GoalStore(goals_db) as store:
        before = store.generation()

    assert _delete_account(port)[0] == 200

    with GoalStore(goals_db) as store:
        assert store.generation() == before + 1  # 진행 중이던 에이전트 주기의 낡은 쓰기는 이제 거절된다
