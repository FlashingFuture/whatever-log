"""Google 로그인이 끝난 뒤 브라우저가 돌아오는 로컬 주소(루프백 리디렉션, RFC 8252)를 받는 일회용 서버."""

import hmac
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from cloud.errors import LoginCancelled, LoginFailed

CALLBACK_PATH = "/callback"
_PAGE = (
    '<!doctype html><html lang="ko"><meta charset="utf-8"><title>whatever.log</title>'
    "<body style=\"font-family:system-ui,sans-serif;margin:3rem\"><p>{message}</p></body></html>"
)
_DONE = "로그인이 완료됐습니다. 이 창을 닫고 whatever.log로 돌아가세요."
_CANCELLED = "로그인이 취소됐습니다. 이 창을 닫아도 됩니다."
_REJECTED = "이 로그인 요청은 처리할 수 없습니다. whatever.log에서 다시 시도해 주세요."


class _Outcome:
    """콜백에서 받은 결과. 인증 코드이거나 취소다."""

    def __init__(self) -> None:
        """아직 아무것도 받지 않은 상태로 시작한다."""
        self.code: str | None = None
        self.cancelled = False


def _handler_for(state: str, outcome: _Outcome) -> type[BaseHTTPRequestHandler]:
    """이 로그인 시도의 state와 결과 보관소에 묶인 요청 처리기를 만든다."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, message: str) -> None:
            body = _PAGE.format(message=message).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # 주소창의 인증 코드가 다른 곳으로 새지 않게, 그리고 이 응답이 남지 않게 한다.
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            """`/callback`만 받는다. state가 맞지 않거나 코드가 없는 요청은 무시하고 계속 기다린다."""
            parts = urlsplit(self.path)
            if parts.path != CALLBACK_PATH:
                self._reply(404, _REJECTED)
                return
            query = parse_qs(parts.query)
            received_state = (query.get("state") or [""])[0]
            if not hmac.compare_digest(received_state.encode("utf-8"), state.encode("utf-8")):
                self._reply(400, _REJECTED)
                return
            if "error" in query:
                outcome.cancelled = True
                self._reply(200, _CANCELLED)
                return
            code = (query.get("code") or [""])[0]
            if not code:
                self._reply(400, _REJECTED)
                return
            outcome.code = code
            self._reply(200, _DONE)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """요청 로그(주소에 인증 코드가 들어 있다)를 남기지 않는다."""

    return Handler


class LoopbackReceiver:
    """`127.0.0.1`의 빈 포트에서 콜백 한 번을 기다리는 서버. `with`로 쓰고, `redirect_uri`를 로그인 요청에 넣는다.

    이 PC 밖에서는 닿지 않게 127.0.0.1에만 바인딩한다. state가 맞는 첫 콜백만 받고, 그 밖의 요청(파비콘,
    남이 만든 콜백)은 응답만 하고 계속 기다린다.
    """

    def __init__(self, state: str) -> None:
        """포트 0으로 바인딩해 OS가 빈 포트를 고르게 한다."""
        self._outcome = _Outcome()
        self._server = HTTPServer(("127.0.0.1", 0), _handler_for(state, self._outcome))
        self._server.timeout = 0.2

    @property
    def redirect_uri(self) -> str:
        """Google이 로그인 뒤에 브라우저를 돌려보낼 주소."""
        return f"http://127.0.0.1:{self._server.server_port}{CALLBACK_PATH}"

    def __enter__(self) -> "LoopbackReceiver":
        """with 문 진입 — 자신을 돌려준다."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """서버 소켓을 닫는다."""
        self._server.server_close()

    def wait_for_code(self, timeout: float) -> str:
        """콜백이 올 때까지 기다려 인증 코드를 돌려준다. 취소면 LoginCancelled, 제한 시간이 지나면 LoginFailed."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._server.handle_request()
            if self._outcome.cancelled:
                raise LoginCancelled
            if self._outcome.code is not None:
                return self._outcome.code
        raise LoginFailed("로그인 시간이 지났습니다. 다시 시도해 주세요.")
