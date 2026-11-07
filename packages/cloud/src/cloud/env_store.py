"""환경 변수로 받은 토큰을 읽기 전용으로 쓰는 저장소(자격 증명 관리자가 없는 환경 — 컨테이너, 시험 서버용).

운영의 기본 경로는 `KeyringTokenStore`(OS 자격 증명 관리자)이고, 이 저장소는 사용자가 명령줄에서 명시적으로
고를 때만 쓴다(예: 동기화 에이전트의 `--token-from-env`). 저장·삭제는 거부한다 — 환경 변수를 이 프로그램이 다시 쓸 수
없고, 토큰을 디스크에 몰래 남기지도 않는다.
"""

import os
from collections.abc import Mapping

from keyring.errors import KeyringError

from cloud.session import Session

DEFAULT_VARIABLE = "WHATEVER_LOG_TOKEN"


class EnvTokenStore:
    """`TokenStore` 구현. 토큰은 환경 변수에서만 읽는다."""

    def __init__(self, variable: str = DEFAULT_VARIABLE, environ: Mapping[str, str] | None = None) -> None:
        """읽을 환경 변수 이름을 정한다(environ은 테스트용)."""
        self._variable = variable
        self._environ = os.environ if environ is None else environ

    def load(self) -> Session | None:
        """환경 변수에 토큰이 있으면 그 세션(만료·이메일 정보는 없다), 비어 있으면 None."""
        token = self._environ.get(self._variable, "").strip()
        return Session(token) if token else None

    def save(self, session: Session) -> None:
        """읽기 전용이라 저장하지 않는다."""
        raise KeyringError("환경 변수 토큰 저장소는 읽기 전용입니다.")

    def clear(self) -> None:
        """읽기 전용이라 지우지 않는다."""
        raise KeyringError("환경 변수 토큰 저장소는 읽기 전용입니다.")
