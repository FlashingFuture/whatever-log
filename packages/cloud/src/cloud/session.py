"""로그인 세션(서버가 발급한 토큰)과 그 저장소 인터페이스."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Session:
    """서버가 발급한 자체 토큰. Google 토큰은 보관하지 않는다(docs/auth-design.md).

    expires_at은 UTC 시각(시간대 정보가 있는 datetime)이고, None이면 만료가 없다.
    """

    token: str
    expires_at: datetime | None = None


class TokenStore(Protocol):
    """세션을 어디에 두는지 감추는 인터페이스. 운영에서는 OS 자격 증명 관리자를, 테스트에서는 메모리를 쓴다.

    `goals.db`·`recorder.db` 같은 기록 DB에는 토큰을 두지 않는다 — 구현은 그 밖의 저장 위치를 써야 한다.
    """

    def load(self) -> Session | None:
        """저장된 세션. 없으면 None."""
        ...

    def save(self, session: Session) -> None:
        """세션을 저장한다(이미 있으면 바꾼다)."""
        ...

    def clear(self) -> None:
        """저장된 세션을 지운다(없어도 오류가 아니다)."""
        ...


class InMemoryTokenStore:
    """메모리에만 두는 저장소. 테스트와, 아직 영구 저장소가 없을 때의 기본값이다(프로그램을 끄면 사라진다)."""

    def __init__(self) -> None:
        """빈 저장소로 시작한다."""
        self._session: Session | None = None

    def load(self) -> Session | None:
        """저장된 세션. 없으면 None."""
        return self._session

    def save(self, session: Session) -> None:
        """세션을 저장한다(이미 있으면 바꾼다)."""
        self._session = session

    def clear(self) -> None:
        """저장된 세션을 지운다(없어도 오류가 아니다)."""
        self._session = None
