"""서버와 통신하는 쪽의 경계. 로그인 상태(Account)와, 서버를 부르는 함수에 로그인을 요구하는 데코레이터를 둔다.

이 패키지에 의존하는 것은 서버를 부르는 쪽(전송 에이전트, 화면의 보고서 기능)뿐이다. recorder·집계·목표 등
로컬 기능은 이 패키지를 쓰지 않으므로 로그인 없이도 항상 동작한다(docs/auth-design.md).
"""

from cloud.account import Account
from cloud.config import CloudConfig, load_config
from cloud.errors import LoginCancelled, LoginFailed, NotSignedIn
from cloud.google_login import sign_in_with_google
from cloud.guard import require_login
from cloud.keyring_store import KeyringTokenStore
from cloud.session import InMemoryTokenStore, Session, TokenStore

__all__ = [
    "Account",
    "CloudConfig",
    "InMemoryTokenStore",
    "KeyringTokenStore",
    "LoginCancelled",
    "LoginFailed",
    "NotSignedIn",
    "Session",
    "TokenStore",
    "load_config",
    "require_login",
    "sign_in_with_google",
]
