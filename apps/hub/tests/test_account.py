import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from hub.__main__ import _Handler
from hub.external_links import LINK_OPENED, LINK_UNKNOWN
from hub.account_service import (
    AccountService,
    AccountUnavailable,
    Identity,
    LoginInProgress,
    LoginProblem,
    LogoutProblem,
    ProviderInfo,
    UnknownProvider,
)

UI_ORIGIN = "http://127.0.0.1:5173"
SECRET_TOKEN = "super-secret-token-value"


class FakePort:
    """CloudPort 가짜. sign_in은 events로 끝낼 때까지 기다리게 할 수 있다."""

    def __init__(self) -> None:
        self.email: str | None = None
        self.outcome: Exception | None = None
        self.release = threading.Event()
        self.started = threading.Event()
        self.hold = False
        self.revoked = True
        self.sign_out_error: LogoutProblem | None = None
        self.calls: list[str] = []

    def providers(self) -> tuple[ProviderInfo, ...]:
        return (ProviderInfo("google", "Google"),)

    def current(self) -> Identity | None:
        return Identity(self.email) if self.email else None

    def sign_in(self, provider_id, *, cancelled) -> None:
        self.calls.append(f"sign_in:{provider_id}")
        self.started.set()
        if self.hold:
            deadline = time.monotonic() + 5
            while not self.release.is_set() and time.monotonic() < deadline:
                if cancelled():
                    raise LoginProblem("로그인을 취소했습니다.", cancelled=True)
                time.sleep(0.01)
        if self.outcome is not None:
            raise self.outcome
        self.email = "a@example.com"

    def sign_out(self) -> bool:
        self.calls.append("sign_out")
        if self.sign_out_error is not None:
            raise self.sign_out_error
        self.email = None
        return self.revoked


def make_service(port: FakePort | None = None) -> tuple[AccountService, FakePort]:
    port = port or FakePort()
    return AccountService(lambda: port), port


def test_signed_out_snapshot_lists_the_providers() -> None:
    service, _ = make_service()

    assert service.snapshot() == {
        "available": True,
        "signed_in": False,
        "email": None,
        "login": {"state": "idle", "message": None},
        "providers": [{"id": "google", "label": "Google"}],
    }


def test_a_successful_login_ends_signed_in() -> None:
    service, _ = make_service()

    service.start_login("google")
    service.wait_for_login(5)

    snapshot = service.snapshot()
    assert snapshot["signed_in"] is True and snapshot["email"] == "a@example.com"
    assert snapshot["login"] == {"state": "idle", "message": None}


def test_login_is_pending_while_the_user_is_in_the_browser() -> None:
    port = FakePort()
    port.hold = True
    service, _ = make_service(port)

    service.start_login("google")
    assert port.started.wait(2)

    assert service.snapshot()["login"]["state"] == "pending"
    assert service.snapshot()["signed_in"] is False
    port.release.set()
    service.wait_for_login(5)
    assert service.snapshot()["login"]["state"] == "idle"


def test_a_second_login_while_pending_is_rejected() -> None:
    port = FakePort()
    port.hold = True
    service, _ = make_service(port)
    service.start_login("google")
    assert port.started.wait(2)

    with pytest.raises(LoginInProgress):
        service.start_login("google")

    port.release.set()
    service.wait_for_login(5)
    assert port.calls.count("sign_in:google") == 1


def test_a_failed_login_keeps_the_message_until_the_next_attempt() -> None:
    port = FakePort()
    port.outcome = LoginProblem("서버에 연결하지 못했습니다.")
    service, _ = make_service(port)

    service.start_login("google")
    service.wait_for_login(5)

    assert service.snapshot()["login"] == {"state": "failed", "message": "서버에 연결하지 못했습니다."}
    port.outcome = None
    service.start_login("google")
    service.wait_for_login(5)
    assert service.snapshot()["login"] == {"state": "idle", "message": None}
    assert service.snapshot()["signed_in"] is True


def test_cancelling_returns_to_idle_without_an_error_message() -> None:
    port = FakePort()
    port.hold = True
    service, _ = make_service(port)
    service.start_login("google")
    assert port.started.wait(2)

    service.cancel_login()
    service.wait_for_login(5)

    snapshot = service.snapshot()
    assert snapshot["login"] == {"state": "idle", "message": None}
    assert snapshot["signed_in"] is False


def test_cancel_with_nothing_pending_does_nothing() -> None:
    service, _ = make_service()

    service.cancel_login()

    assert service.snapshot()["login"]["state"] == "idle"


def test_an_unexpected_error_in_the_login_thread_becomes_a_generic_failure() -> None:
    port = FakePort()
    port.outcome = RuntimeError("secret internals")
    service, _ = make_service(port)

    service.start_login("google")
    service.wait_for_login(5)

    login = service.snapshot()["login"]
    assert login["state"] == "failed" and "secret internals" not in login["message"]


def test_an_unknown_provider_is_rejected_before_anything_starts() -> None:
    service, port = make_service()

    with pytest.raises(UnknownProvider):
        service.start_login("kakao")

    assert port.calls == []


def test_sign_out_clears_the_login_and_reports_server_revocation() -> None:
    service, port = make_service()
    port.email = "a@example.com"

    assert service.sign_out() is True
    assert service.snapshot()["signed_in"] is False

    port.email, port.revoked = "a@example.com", False
    assert service.sign_out() is False  # 서버에 닿지 못해도 이 PC에서는 로그아웃된다


def test_sign_out_during_a_pending_login_cancels_it() -> None:
    port = FakePort()
    port.hold = True
    service, _ = make_service(port)
    service.start_login("google")
    assert port.started.wait(2)

    service.sign_out()
    service.wait_for_login(5)

    snapshot = service.snapshot()
    assert snapshot["signed_in"] is False and snapshot["login"]["state"] == "idle"


def test_a_stale_login_thread_cannot_overwrite_a_newer_attempt() -> None:
    first = FakePort()
    first.hold = True
    service, _ = make_service(first)
    service.start_login("google")
    assert first.started.wait(2)
    service.cancel_login()
    service.wait_for_login(5)

    first.hold = False
    service.start_login("google")
    service.wait_for_login(5)

    assert service.snapshot()["signed_in"] is True
    assert service.snapshot()["login"]["state"] == "idle"


def test_without_cloud_the_account_is_unavailable_but_nothing_raises() -> None:
    def broken() -> FakePort:
        raise AccountUnavailable

    service = AccountService(broken)

    snapshot = service.snapshot()
    assert snapshot["available"] is False and snapshot["providers"] == []
    with pytest.raises(AccountUnavailable):
        service.start_login("google")
    with pytest.raises(AccountUnavailable):
        service.sign_out()


def test_a_crashing_factory_is_also_treated_as_unavailable() -> None:
    def crashing() -> FakePort:
        raise OSError("keyring backend exploded")

    assert AccountService(crashing).snapshot()["available"] is False


def test_the_port_is_created_lazily_and_only_once() -> None:
    created: list[int] = []

    def factory() -> FakePort:
        created.append(1)
        return FakePort()

    service = AccountService(factory)
    assert created == []

    service.snapshot()
    service.snapshot()

    assert created == [1]


# --- HTTP ---------------------------------------------------------------------------------------------


@pytest.fixture
def account_server():
    """가짜 CloudPort를 단 실제 hub 서버. (주소, 포트 객체, 열린 링크 목록)을 돌려준다."""
    port = FakePort()
    opened: list[str] = []
    previous = (_Handler.account, _Handler.link_opener, _Handler.allowed_origins)
    _Handler.account = AccountService(lambda: port)
    _Handler.link_opener = staticmethod(lambda name: (opened.append(name), LINK_OPENED if name == "privacy" else LINK_UNKNOWN)[1])
    _Handler.allowed_origins = frozenset({UI_ORIGIN})
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_port, port, opened
    finally:
        server.shutdown()
        server.server_close()
        _Handler.account, _Handler.allowed_origins = previous[0], previous[2]
        _Handler.link_opener = staticmethod(previous[1])  # 클래스에서 읽으면 풀려 나오므로 다시 감싸서 되돌린다


def call(port: int, method: str, path: str, body=None, *, origin: str | None = UI_ORIGIN, host: str | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {}
    payload = None
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, (json.loads(raw) if raw else None), response


def test_get_account_returns_the_state_without_any_token(account_server) -> None:
    port, fake, _ = account_server
    fake.email = "a@example.com"

    status, body, response = call(port, "GET", "/api/account")

    assert status == 200
    assert body["signed_in"] is True and body["email"] == "a@example.com"
    assert set(body) == {"available", "signed_in", "email", "login", "providers", "sync_enabled"}
    assert response.getheader("Access-Control-Allow-Origin") == UI_ORIGIN


def test_login_starts_with_202_and_the_result_arrives_through_get(account_server) -> None:
    port, fake, _ = account_server
    fake.hold = True

    status, body, _ = call(port, "POST", "/api/account/login", {"provider": "google"})

    assert status == 202 and body["login"]["state"] == "pending"
    fake.release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _, body, _ = call(port, "GET", "/api/account")
        if body["signed_in"]:
            break
        time.sleep(0.02)
    assert body["signed_in"] is True and body["email"] == "a@example.com"


def test_a_second_login_request_while_pending_is_409(account_server) -> None:
    port, fake, _ = account_server
    fake.hold = True
    call(port, "POST", "/api/account/login", {"provider": "google"})
    assert fake.started.wait(2)

    status, body, _ = call(port, "POST", "/api/account/login", {"provider": "google"})

    assert status == 409 and body["error"]["code"] == "invalid_request"
    fake.release.set()


@pytest.mark.parametrize(
    "body",
    [{}, {"provider": 5}, {"provider": "kakao"}, {"provider": "google", "extra": 1}, {"provide": "google"}],
)
def test_invalid_login_bodies_are_400(account_server, body) -> None:
    port, fake, _ = account_server

    status, _, _ = call(port, "POST", "/api/account/login", body)

    assert status == 400
    assert fake.calls == []


def test_delete_login_cancels_it(account_server) -> None:
    port, fake, _ = account_server
    fake.hold = True
    call(port, "POST", "/api/account/login", {"provider": "google"})
    assert fake.started.wait(2)

    status, _, _ = call(port, "DELETE", "/api/account/login")

    assert status == 200
    _Handler.account.wait_for_login(5)
    assert call(port, "GET", "/api/account")[1]["login"]["state"] == "idle"


def test_logout_clears_and_reports_server_revocation(account_server) -> None:
    port, fake, _ = account_server
    fake.email = "a@example.com"

    status, body, _ = call(port, "POST", "/api/account/logout")

    assert status == 200
    assert body["signed_in"] is False and body["revoked_on_server"] is True


def test_a_failed_local_logout_is_reported_as_an_error(account_server) -> None:
    port, fake, _ = account_server
    fake.email = "a@example.com"
    fake.sign_out_error = LogoutProblem("이 PC의 로그인 정보를 지우지 못했습니다.")

    status, body, _ = call(port, "POST", "/api/account/logout")

    assert status == 500 and "지우지 못했습니다" in body["error"]["message"]


WRITES = [
    ("POST", "/api/account/login", {"provider": "google"}),
    ("POST", "/api/account/logout", None),
    ("DELETE", "/api/account/login", None),
    ("POST", "/api/links/open", {"link": "privacy"}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
@pytest.mark.parametrize("origin", [None, "http://evil.example", "http://localhost:9999", "http://127.0.0.1:5174"])
def test_account_writes_need_the_exact_ui_origin(account_server, method, path, body, origin) -> None:
    port, fake, opened = account_server

    status, _, _ = call(port, method, path, body, origin=origin)

    assert status == 403
    assert fake.calls == [] and opened == []


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_account_writes_reject_a_foreign_host(account_server, method, path, body) -> None:
    port, fake, opened = account_server

    status, _, _ = call(port, method, path, body, host="evil.example")

    assert status == 403
    assert fake.calls == [] and opened == []


def test_logout_and_cancel_reject_a_body(account_server) -> None:
    port, fake, _ = account_server

    assert call(port, "POST", "/api/account/logout", {"x": 1})[0] == 400
    assert call(port, "DELETE", "/api/account/login", {"x": 1})[0] == 400
    assert fake.calls == []


def test_login_needs_a_json_content_type(account_server) -> None:
    port, fake, _ = account_server
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(
        "POST",
        "/api/account/login",
        body='{"provider": "google"}',
        headers={"Origin": UI_ORIGIN, "Content-Type": "text/plain"},
    )

    assert connection.getresponse().status == 415
    assert fake.calls == []


def test_an_unavailable_cloud_gives_503_for_actions_but_get_still_answers(account_server) -> None:
    port, _, _ = account_server

    def broken() -> FakePort:
        raise AccountUnavailable

    _Handler.account = AccountService(broken)

    status, body, _ = call(port, "GET", "/api/account")
    assert status == 200 and body["available"] is False
    assert call(port, "POST", "/api/account/login", {"provider": "google"})[0] == 503
    assert call(port, "POST", "/api/account/logout")[0] == 503


def test_open_link_only_opens_listed_links(account_server) -> None:
    port, _, opened = account_server

    assert call(port, "POST", "/api/links/open", {"link": "privacy"})[0] == 204
    assert call(port, "POST", "/api/links/open", {"link": "https://evil.example"})[0] == 400
    assert call(port, "POST", "/api/links/open", {"link": "privacy", "url": "x"})[0] == 400
    assert call(port, "POST", "/api/links/open", {})[0] == 400
    assert opened == ["privacy", "https://evil.example"]  # 목록 판단은 opener(open_link)가 한다


def test_the_real_link_table_has_only_the_privacy_doc() -> None:
    from hub.external_links import LINKS, open_link

    opened: list[str] = []

    assert list(LINKS) == ["privacy"]
    assert LINKS["privacy"].startswith("https://github.com/FlashingFuture/whatever-log/")
    assert open_link("privacy", lambda url: opened.append(url) or True) == "opened"
    assert open_link("https://evil.example", lambda url: opened.append(url) or True) == "unknown"
    assert opened == [LINKS["privacy"]]


def test_a_browser_that_cannot_open_is_reported_so_the_ui_can_fall_back(account_server) -> None:
    from hub.external_links import LINK_FAILED

    port, _, _ = account_server
    _Handler.link_opener = staticmethod(lambda name: LINK_FAILED)

    status, body, _ = call(port, "POST", "/api/links/open", {"link": "privacy"})

    assert status == 503 and body["error"]["code"] == "unavailable"


def test_open_link_reports_a_false_or_raising_browser_as_failed() -> None:
    from hub.external_links import open_link

    def broken(url):
        raise OSError("no browser")

    assert open_link("privacy", lambda url: False) == "failed"
    assert open_link("privacy", broken) == "failed"
    assert open_link("privacy", lambda url: True) == "opened"


def test_the_account_state_tells_whether_goal_sync_was_turned_on(account_server, tmp_path) -> None:
    from goals import META_SYNC_ENABLED, GoalStore

    port, _, _ = account_server
    saved = _Handler.goals_db_path
    _Handler.goals_db_path = tmp_path / "goals.db"
    try:
        assert call(port, "GET", "/api/account")[1]["sync_enabled"] is False
        with GoalStore(_Handler.goals_db_path) as store:
            store.set_meta(META_SYNC_ENABLED, "1")
        assert call(port, "GET", "/api/account")[1]["sync_enabled"] is True
    finally:
        _Handler.goals_db_path = saved
