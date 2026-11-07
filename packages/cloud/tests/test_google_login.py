import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from cloud import CloudConfig, LoginCancelled, LoginFailed, pkce, sign_in_with_google
from cloud.google_login import AUTH_URL, build_auth_url

CONFIG = CloudConfig(server_url="https://server.example", google_client_id="client-123")


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def test_the_login_url_asks_only_for_the_email_with_pkce_and_state() -> None:
    url = build_auth_url(client_id="client-123", redirect_uri="http://127.0.0.1:5000/callback", challenge="chal", state="st")

    assert url.startswith(f"{AUTH_URL}?")
    assert _query(url) == {
        "client_id": "client-123",
        "redirect_uri": "http://127.0.0.1:5000/callback",
        "response_type": "code",
        "scope": "openid email",
        "code_challenge": "chal",
        "code_challenge_method": "S256",
        "state": "st",
    }


class _Browser:
    """시스템 브라우저를 흉내 낸다. 열린 로그인 주소에서 redirect_uri와 state를 읽어, 사용자가 로그인한 것처럼 콜백을 친다."""

    def __init__(self, respond) -> None:
        self.opened: list[str] = []
        self._respond = respond
        self.threads: list[threading.Thread] = []

    def __call__(self, url: str) -> bool:
        self.opened.append(url)
        query = _query(url)
        thread = threading.Thread(target=self._respond, args=(query,))
        thread.start()
        self.threads.append(thread)
        return True


def _hit(redirect_uri: str, **params: str) -> None:
    from urllib.parse import urlencode

    try:
        urllib.request.urlopen(f"{redirect_uri}?{urlencode(params)}", timeout=3).read()
    except urllib.error.HTTPError:
        pass  # 거부된 콜백(state 불일치 등)은 브라우저에 400이 돌아온다


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def read(self, limit: int = -1) -> bytes:
        return self._body


def test_the_full_flow_exchanges_the_code_with_the_verifier_for_a_session() -> None:
    sent: list[dict] = []
    shown: list[str] = []

    def opener(request, timeout):
        sent.append({"url": request.full_url, "body": json.loads(request.data)})
        return _Response({"token": "tok", "expires_at": "2026-12-06T03:00:00Z", "email": "a@example.com"})

    browser = _Browser(lambda q: _hit(q["redirect_uri"], code="auth-code", state=q["state"]))

    session = sign_in_with_google(CONFIG, show_url=shown.append, open_browser=browser, timeout=5, opener=opener)

    assert session.token == "tok" and session.email == "a@example.com"
    assert session.expires_at == datetime(2026, 12, 6, 3, 0, tzinfo=UTC)
    assert shown == browser.opened and len(shown) == 1  # 브라우저를 못 열어도 쓸 수 있게 주소를 알려 준다
    (call,) = sent
    assert call["url"] == "https://server.example/auth/google"
    assert call["body"]["code"] == "auth-code"
    # 서버로 가는 verifier는 로그인 주소의 challenge와 짝이 맞아야 하고, 로그인 주소에는 verifier가 없어야 한다.
    assert pkce.code_challenge(call["body"]["code_verifier"]) == _query(shown[0])["code_challenge"]
    assert call["body"]["code_verifier"] not in shown[0]
    assert call["body"]["redirect_uri"] == _query(shown[0])["redirect_uri"]


def test_cancelling_at_google_raises_login_cancelled_without_calling_the_server() -> None:
    calls: list = []
    browser = _Browser(lambda q: _hit(q["redirect_uri"], error="access_denied", state=q["state"]))

    with pytest.raises(LoginCancelled):
        sign_in_with_google(CONFIG, open_browser=browser, timeout=5, opener=lambda *a, **k: calls.append(a))

    assert calls == []


def test_a_callback_with_a_forged_state_is_not_accepted() -> None:
    calls: list = []
    browser = _Browser(lambda q: _hit(q["redirect_uri"], code="evil", state="forged"))

    with pytest.raises(LoginFailed, match="시간이 지났습니다"):
        sign_in_with_google(CONFIG, open_browser=browser, timeout=0.6, opener=lambda *a, **k: calls.append(a))

    assert calls == []


def test_timing_out_while_waiting_for_the_user_fails_cleanly() -> None:
    with pytest.raises(LoginFailed, match="시간이 지났습니다"):
        sign_in_with_google(CONFIG, open_browser=lambda url: True, timeout=0.3)


def test_a_browser_that_cannot_open_does_not_stop_the_flow() -> None:
    shown: list[str] = []

    def broken_browser(url: str) -> bool:
        raise OSError("no browser")

    def opener(request, timeout):
        return _Response({"token": "tok", "expires_at": "2026-12-06T03:00:00Z"})

    def user_opens_the_shown_url() -> None:
        while not shown:
            pass
        query = _query(shown[0])
        _hit(query["redirect_uri"], code="c", state=query["state"])

    thread = threading.Thread(target=user_opens_the_shown_url)
    thread.start()

    session = sign_in_with_google(CONFIG, show_url=shown.append, open_browser=broken_browser, timeout=5, opener=opener)
    thread.join()

    assert session.token == "tok"


def test_server_rejections_are_reported_as_login_failed() -> None:
    import urllib.error

    def opener(request, timeout):
        raise urllib.error.URLError("down")

    browser = _Browser(lambda q: _hit(q["redirect_uri"], code="c", state=q["state"]))

    with pytest.raises(LoginFailed, match="연결하지 못했습니다"):
        sign_in_with_google(CONFIG, open_browser=browser, timeout=5, opener=opener)


def test_a_login_cancelled_just_as_the_code_arrives_is_not_exchanged() -> None:
    import time

    calls: list = []
    started = time.monotonic()

    def respond(query):
        time.sleep(0.3)  # 콜백은 0.3초에 도착하고, 앱의 취소는 0.35초에 보인다 — 코드가 도착한 직후다
        _hit(query["redirect_uri"], code="late-code", state=query["state"])

    browser = _Browser(respond)

    with pytest.raises(LoginCancelled):
        sign_in_with_google(
            CONFIG,
            open_browser=browser,
            timeout=5,
            cancelled=lambda: time.monotonic() - started > 0.35,
            opener=lambda *args, **kwargs: calls.append(args),
        )
    for thread in browser.threads:
        thread.join()

    assert calls == []  # 서버에 코드를 보내지 않았다


def test_a_login_cancelled_during_the_exchange_discards_and_revokes_the_token() -> None:
    sent: list[str] = []
    state = {"cancel": False}

    def opener(request, timeout):
        sent.append(request.full_url)
        if request.full_url.endswith("/auth/google"):
            state["cancel"] = True  # 교환하는 동안 취소 버튼을 눌렀다
            return _Response({"token": "issued-token", "expires_at": "2026-12-06T03:00:00Z"})
        assert request.headers["Authorization"] == "Bearer issued-token"
        revoked = _Response({})
        revoked.status = 204
        return revoked

    browser = _Browser(lambda q: _hit(q["redirect_uri"], code="c", state=q["state"]))

    with pytest.raises(LoginCancelled):
        sign_in_with_google(CONFIG, open_browser=browser, timeout=5, cancelled=lambda: state["cancel"], opener=opener)

    assert sent == ["https://server.example/auth/google", "https://server.example/auth/logout"]


def test_a_login_cancelled_while_the_receiver_is_closing_is_not_exchanged(monkeypatch) -> None:
    import cloud.google_login as module

    calls: list = []
    state = {"cancel": False}
    original_exit = module.LoopbackReceiver.__exit__

    def exit_then_cancel(self, *exc_info):
        original_exit(self, *exc_info)
        state["cancel"] = True  # 코드를 받고 수신기를 닫은 직후에 취소됐다

    monkeypatch.setattr(module.LoopbackReceiver, "__exit__", exit_then_cancel)
    browser = _Browser(lambda q: _hit(q["redirect_uri"], code="c", state=q["state"]))

    with pytest.raises(LoginCancelled):
        sign_in_with_google(
            CONFIG,
            open_browser=browser,
            timeout=5,
            cancelled=lambda: state["cancel"],
            opener=lambda *args, **kwargs: calls.append(args),
        )

    assert calls == []
