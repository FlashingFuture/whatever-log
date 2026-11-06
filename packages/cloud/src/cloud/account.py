"""로그인 상태. 서버를 부르는 코드가 "지금 로그인되어 있는가"를 한곳에서 묻는다."""

from collections.abc import Callable
from datetime import UTC, datetime

from cloud.errors import NotSignedIn
from cloud.session import Session, TokenStore


class Account:
    """저장소의 세션과 시계로 로그인 여부를 판단한다.

    now는 시각을 만드는 함수다(테스트가 시계를 고정할 수 있게 주입한다). 만료된 세션은 "로그인 안 됨"으로
    보지만 저장소에서 지우지는 않는다 — 나중에 토큰 갱신을 붙일 때 같은 세션을 쓸 수 있게 둔다.
    """

    def __init__(self, store: TokenStore, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        """세션을 읽고 쓸 저장소와 시계를 받는다."""
        self._store = store
        self._now = now

    def session(self) -> Session | None:
        """유효한 세션. 없거나 만료됐으면 None."""
        session = self._store.load()
        if session is None:
            return None
        if session.expires_at is not None and session.expires_at <= self._now():
            return None
        return session

    def is_signed_in(self) -> bool:
        """로그인되어 있는지(화면이 로그인 버튼을 보일지 정할 때 쓴다)."""
        return self.session() is not None

    def sign_in(self, session: Session) -> None:
        """로그인 흐름이 끝나 받은 세션을 저장한다."""
        self._store.save(session)

    def sign_out(self) -> None:
        """로그아웃한다. 저장된 세션을 지운다."""
        self._store.clear()

    def require_session(self) -> Session:
        """유효한 세션을 돌려주고, 없으면 NotSignedIn을 던진다."""
        session = self.session()
        if session is None:
            raise NotSignedIn
        return session
