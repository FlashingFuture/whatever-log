"""OS 자격 증명 관리자(Windows는 Credential Manager)에 세션을 두는 저장소."""

import json
from datetime import datetime

import keyring
import keyring.errors

from cloud.session import Session

SERVICE_NAME = "whatever.log"
USERNAME = "session"


_INSECURE_MARKERS = ("plaintext", "uncrypted", "keyrings.alt", "backends.null")


def _require_secure_backend() -> None:
    """토큰이 평문 파일에 남거나(PlaintextKeyring) 어디에도 저장되지 않는(null) 백엔드면 저장을 거부한다."""
    backend = keyring.get_keyring()
    active = getattr(backend, "backends", None)  # 체인 백엔드는 우선순위가 가장 높은 것이 실제로 쓰인다
    if active:
        backend = active[0]
    kind = f"{type(backend).__module__}.{type(backend).__name__}".lower()
    if any(marker in kind for marker in _INSECURE_MARKERS):
        raise keyring.errors.KeyringError("안전한 OS 자격 증명 관리자가 없어 로그인 정보를 저장하지 않았습니다.")


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
            expiry = datetime.fromisoformat(expires_at) if expires_at else None
            if expiry is not None and expiry.tzinfo is None:
                return None  # 시간대 없는 시각은 UTC 시계와 비교할 수 없다 — 깨진 항목으로 본다
            return Session(token=token, expires_at=expiry, email=email if isinstance(email, str) else None)
        except (ValueError, KeyError, TypeError, AttributeError):
            return None

    def save(self, session: Session) -> None:
        """세션을 저장한다(이미 있으면 바꾼다). 자격 증명 관리자를 쓸 수 없거나 평문으로 저장하는 백엔드면 KeyringError를 올린다."""
        _require_secure_backend()
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
            # 항목이 없어서 난 오류인지, 지우지 못해서 난 오류인지 오류만으로는 알 수 없다 — 아직 남아 있으면 실패다.
            if keyring.get_password(self._service, self._username) is not None:
                raise
