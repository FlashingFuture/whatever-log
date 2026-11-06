"""서버(`POST /auth/google`)에 인증 코드를 보내 로그인 토큰을 받는다."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from cloud.errors import LoginFailed
from cloud.session import Session

_TIMEOUT_SECONDS = 20
_MAX_RESPONSE_BYTES = 16 * 1024

Opener = Callable[..., Any]


def _error_message(body: bytes) -> str | None:
    """서버가 준 오류 본문 `{"error": {"message"}}`에서 사용자에게 보여 줄 문장을 꺼낸다. 모양이 다르면 None."""
    try:
        message = json.loads(body)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return None
    return message if isinstance(message, str) and 0 < len(message) <= 200 else None


def _parse_session(body: bytes) -> Session:
    """성공 응답 `{token, expires_at, email}`을 검사해 Session으로 만든다. 모양이 다르면 LoginFailed."""
    try:
        data = json.loads(body)
        token = data["token"]
        expires_at = datetime.fromisoformat(data["expires_at"])
        email = data.get("email")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise LoginFailed("서버 응답을 이해하지 못했습니다.") from None
    if not isinstance(token, str) or not token or expires_at.tzinfo is None:
        raise LoginFailed("서버 응답을 이해하지 못했습니다.")
    return Session(token=token, expires_at=expires_at, email=email if isinstance(email, str) else None)


def exchange_code(
    server_url: str,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    opener: Opener = urllib.request.urlopen,
) -> Session:
    """인증 코드·PKCE verifier·리디렉션 주소를 서버에 보내 로그인 토큰을 받는다.

    서버가 Google과 코드를 교환하므로 이 앱은 클라이언트 비밀을 갖지 않는다. 실패하면 서버가 준 사용자용
    메시지(있으면)로 LoginFailed를 올리고, 코드·토큰은 메시지에 담지 않는다. opener는 테스트용이다.
    """
    request = urllib.request.Request(
        f"{server_url}/auth/google",
        data=json.dumps({"code": code, "code_verifier": code_verifier, "redirect_uri": redirect_uri}).encode("utf-8"),
        # urllib 기본 User-Agent(Python-urllib)는 Cloudflare가 봇으로 보고 서버에 닿기 전에 403(1010)으로 막는다.
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "whatever-log-desktop"},
        method="POST",
    )
    try:
        with opener(request, timeout=_TIMEOUT_SECONDS) as response:
            return _parse_session(response.read(_MAX_RESPONSE_BYTES))
    except urllib.error.HTTPError as error:
        message = _error_message(error.read(_MAX_RESPONSE_BYTES))
        raise LoginFailed(message or f"서버가 로그인을 거부했습니다({error.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise LoginFailed("서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.") from None
