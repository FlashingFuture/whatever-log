"""Google 로그인 흐름: 시스템 브라우저로 로그인 → 루프백으로 인증 코드를 받음 → 서버에서 토큰으로 교환."""

import webbrowser
from collections.abc import Callable
from urllib.parse import urlencode

from cloud import pkce
from cloud.config import CloudConfig
from cloud.errors import LoginCancelled
from cloud.loopback import LoopbackReceiver
from cloud.server_client import Opener, exchange_code, revoke_session
from cloud.session import Session

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
LOGIN_TIMEOUT_SECONDS = 180


def build_auth_url(*, client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    """Google 로그인 주소. 이메일만 요청한다(`openid email`) — 이름·프로필·드라이브 같은 범위는 요청하지 않는다."""
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def sign_in_with_google(
    config: CloudConfig,
    *,
    show_url: Callable[[str], None] = lambda url: None,
    open_browser: Callable[[str], object] = webbrowser.open,
    timeout: float = LOGIN_TIMEOUT_SECONDS,
    cancelled: Callable[[], bool] = lambda: False,
    opener: Opener | None = None,
) -> Session:
    """로그인을 끝까지 진행해 서버가 발급한 Session을 돌려준다(저장은 호출부가 Account로 한다).

    1. PKCE 값과 state를 만들고 루프백 서버를 연다. 2. 시스템 브라우저로 Google 로그인을 연다(임베디드
    웹뷰는 Google이 막는다). 브라우저를 못 열어도 쓸 수 있게 주소는 show_url로도 알린다. 3. 돌아온 인증 코드를
    서버에 보내 토큰을 받는다. 취소(Google 화면에서, 또는 cancelled()가 True)면 LoginCancelled, 그 밖의 실패는
    LoginFailed다.
    """
    verifier = pkce.new_code_verifier()
    state = pkce.new_state()
    with LoopbackReceiver(state) as receiver:
        url = build_auth_url(
            client_id=config.google_client_id,
            redirect_uri=receiver.redirect_uri,
            challenge=pkce.code_challenge(verifier),
            state=state,
        )
        show_url(url)
        try:
            open_browser(url)
        except Exception:  # 브라우저가 없는 환경 — 사용자가 show_url로 알려 준 주소를 직접 연다
            pass
        code = receiver.wait_for_code(timeout, cancelled)
        redirect_uri = receiver.redirect_uri
    if cancelled():  # 루프백 서버를 닫는 사이에 취소됐다면 코드를 서버에 보내지 않는다
        raise LoginCancelled
    kwargs = {} if opener is None else {"opener": opener}
    session = exchange_code(config.server_url, code=code, code_verifier=verifier, redirect_uri=redirect_uri, **kwargs)
    if cancelled():
        # 교환 중에 취소됐다. 받은 토큰은 저장하지 않고 서버에서 폐기를 시도한다(실패해도 취소로 끝난다).
        revoke_session(config.server_url, session.token, **kwargs)
        raise LoginCancelled
    return session
