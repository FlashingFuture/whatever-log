"""OS 자격 증명 관리자(Windows는 Credential Manager)에 세션을 두는 저장소."""

import json
from datetime import datetime

import keyring
import keyring.errors

from cloud.session import Session

SERVICE_NAME = "whatever.log"
USERNAME = "session"


class KeyringTokenStore:
    """토큰을 `goals.db`·`recorder.db`가 아니라 OS 자격 증명 관리자에 둔다(기록 DB를 복사·백업해도 토큰이 따라가지 않는다).

    저장된 값이 깨졌거나 자격 증명 관리자를 쓸 수 없으면 load는 "로그인 안 됨"(None)으로 본다 — 로그인이 안
    되어 있어도 로컬 기능은 돌아가야 하기 때문이다. 쓰기(save)는 실패를 숨기지 않고 올린다.
    """

    def __init__(self, service: str = SERVICE_NAME, username: str = USERNAME) -> None:
        """자격 증명 항목의 이름(서비스, 사용자)을 정한다. 테스트는 다른 이름을 쓴다."""
        self._service = service
        self._username = username

    def load(self) -> Session | None:
        """저장된 세션. 없거나 읽을 수 없거나 형식이 깨졌으면 None."""
        try:
            raw = keyring.get_password(self._service, self._username)
        except keyring.errors.KeyringError:
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            token = data["token"]
            expires_at = data.get("expires_at")
            email = data.get("email")
            if not isinstance(token, str) or not token:
                return None
            return Session(
                token=token,
                expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
                email=email if isinstance(email, str) else None,
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    def save(self, session: Session) -> None:
        """세션을 저장한다(이미 있으면 바꾼다). 자격 증명 관리자를 쓸 수 없으면 오류를 올린다."""
        value = json.dumps(
            {
                "token": session.token,
                "expires_at": session.expires_at.isoformat() if session.expires_at else None,
                "email": session.email,
            }
        )
        keyring.set_password(self._service, self._username, value)

    def clear(self) -> None:
        """저장된 세션을 지운다(없어도 오류가 아니다)."""
        try:
            keyring.delete_password(self._service, self._username)
        except keyring.errors.PasswordDeleteError:
            pass  # 이미 없다
