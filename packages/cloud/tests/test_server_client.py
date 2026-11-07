import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cloud import Session
from cloud.errors import LoginFailed
from cloud.server_client import exchange_code

ARGS = {"code": "4/0Code", "code_verifier": "v" * 43, "redirect_uri": "http://127.0.0.1:5000/callback"}


class _FakeServer:
    """`POST /auth/google`을 흉내 내는 실제 HTTP 서버. 받은 요청을 기록하고 정해 둔 응답을 돌려준다."""

    def __init__(self, status: int, body: bytes) -> None:
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append(
                    {
                        "path": self.path,
                        "type": self.headers["Content-Type"],
                        "agent": self.headers["User-Agent"],
                        "auth": self.headers["Authorization"],
                        "body": json.loads(raw) if raw else None,
                    }
                )
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve():
    servers: list[_FakeServer] = []

    def make(status: int, body: object) -> _FakeServer:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        servers.append(_FakeServer(status, raw))
        return servers[-1]

    yield make
    for server in servers:
        server.close()


def test_it_posts_code_verifier_and_redirect_uri_and_returns_the_session(serve) -> None:
    server = serve(200, {"token": "tok-123", "expires_at": "2026-12-06T03:00:00.000Z", "email": "a@example.com"})

    session = exchange_code(server.url, **ARGS)

    assert session == Session("tok-123", datetime(2026, 12, 6, 3, 0, tzinfo=UTC), "a@example.com")
    (request,) = server.requests
    assert request["path"] == "/auth/google" and request["type"] == "application/json"
    assert request["body"] == {"code": "4/0Code", "code_verifier": "v" * 43, "redirect_uri": ARGS["redirect_uri"]}


def test_it_does_not_use_the_default_python_user_agent(serve) -> None:
    # Cloudflare는 Python-urllib을 봇으로 보고 서버에 닿기 전에 403(error 1010)으로 막는다.
    server = serve(200, {"token": "t", "expires_at": "2026-12-06T03:00:00Z"})

    exchange_code(server.url, **ARGS)

    assert not server.requests[0]["agent"].startswith("Python-urllib")


def test_the_server_message_is_shown_for_known_errors(serve) -> None:
    server = serve(400, {"error": {"code": "invalid_grant", "message": "인증 코드가 만료됐거나 이미 사용됐습니다."}})

    with pytest.raises(LoginFailed, match="인증 코드가 만료됐거나"):
        exchange_code(server.url, **ARGS)


def test_unreadable_error_bodies_fall_back_to_the_status(serve) -> None:
    for body in (b"<html>bad gateway</html>", b"{}", b'{"error": 5}', json.dumps({"error": {"message": "x" * 500}}).encode()):
        server = serve(502, body)

        with pytest.raises(LoginFailed, match="502"):
            exchange_code(server.url, **ARGS)


def test_malformed_success_bodies_are_rejected(serve) -> None:
    bad_bodies = [
        b"not json",
        b"[]",
        {"expires_at": "2026-12-06T03:00:00Z"},  # 토큰 없음
        {"token": "", "expires_at": "2026-12-06T03:00:00Z"},
        {"token": 5, "expires_at": "2026-12-06T03:00:00Z"},
        {"token": "t", "expires_at": "yesterday"},
        {"token": "t", "expires_at": "2026-12-06T03:00:00"},  # 시간대 없음
        {"token": "t"},
    ]
    for body in bad_bodies:
        server = serve(200, body)

        with pytest.raises(LoginFailed, match="이해하지 못했습니다"):
            exchange_code(server.url, **ARGS)


def test_a_missing_email_is_allowed(serve) -> None:
    server = serve(200, {"token": "t", "expires_at": "2026-12-06T03:00:00Z"})

    assert exchange_code(server.url, **ARGS).email is None


def test_an_unreachable_server_is_a_friendly_error() -> None:
    with pytest.raises(LoginFailed, match="연결하지 못했습니다"):
        exchange_code("http://127.0.0.1:1", **ARGS)  # 포트 1은 닫혀 있다


def test_error_messages_never_contain_the_code(serve) -> None:
    server = serve(500, b"boom")

    with pytest.raises(LoginFailed) as caught:
        exchange_code(server.url, **ARGS)

    assert "4/0Code" not in str(caught.value) and "v" * 43 not in str(caught.value)


def test_an_error_response_cut_off_mid_body_still_becomes_login_failed() -> None:
    import http.client
    import urllib.error

    class _Cut(urllib.error.HTTPError):
        def read(self, *args):
            raise http.client.IncompleteRead(b"")

    def opener(request, timeout):
        raise _Cut("https://s", 502, "bad gateway", {}, None)

    with pytest.raises(LoginFailed, match="502"):
        exchange_code("https://s", opener=opener, **ARGS)


def test_revoke_posts_the_bearer_token_and_reports_success(serve) -> None:
    from cloud.server_client import revoke_session

    server = serve(204, b"")

    assert revoke_session(server.url, "tok-123") is True
    (request,) = server.requests
    assert request["path"] == "/auth/logout" and request["auth"] == "Bearer tok-123"
    assert not request["agent"].startswith("Python-urllib")


def test_revoke_never_raises_and_reports_failure(serve) -> None:
    from cloud.server_client import revoke_session

    assert revoke_session(serve(401, {"error": {"message": "x"}}).url, "tok") is False
    assert revoke_session("http://127.0.0.1:9", "tok") is False  # 연결할 수 없는 서버


class _Redirector:
    """다른 출처로 3xx를 돌려주는 서버와, 그 다른 출처에서 받은 요청을 기록하는 서버."""

    def __init__(self) -> None:
        self.elsewhere = _FakeServer(200, {"goals": [], "token": "stolen", "expires_at": "2026-12-06T03:00:00Z"})
        target = self.elsewhere.url
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _redirect(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                self.send_response(307)  # 307은 메서드·본문·헤더를 그대로 다시 보내라는 뜻이다
                self.send_header("Location", f"{target}{self.path}")
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = do_PUT = do_DELETE = _redirect

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.outer = outer

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.elsewhere.close()


@pytest.fixture
def redirector():
    server = _Redirector()
    yield server
    server.close()


def test_a_redirect_to_another_origin_never_carries_the_token_or_the_code(redirector) -> None:
    from cloud import ServerApi, ServerError
    from cloud.server_client import revoke_session

    with pytest.raises(ServerError) as raised:
        ServerApi(redirector.url, "secret-token").list_goals()
    assert raised.value.code == "redirect"

    assert revoke_session(redirector.url, "secret-token") is False
    with pytest.raises(LoginFailed):
        exchange_code(redirector.url, **ARGS)

    assert redirector.elsewhere.requests == []  # 다른 출처는 어떤 요청도 받지 못했다
