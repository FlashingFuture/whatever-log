"""PKCE(RFC 7636)와 state 값. 데스크톱 앱은 클라이언트 비밀을 숨길 수 없는 공개 클라이언트라서, 인증 코드를
가로채도 쓸 수 없게 코드를 요청한 쪽만 아는 비밀(verifier)을 함께 쓴다."""

import base64
import hashlib
import secrets


def new_code_verifier() -> str:
    """코드 교환 때 보여 줄 무작위 비밀. 86자(허용 범위 43~128), `A-Za-z0-9-_`만 쓴다."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """verifier의 SHA-256을 base64url(패딩 없음)로 만든 값. 로그인 요청에는 이것만 보내고 verifier는 숨긴다."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_state() -> str:
    """로그인 요청과 콜백을 짝지어 주는 무작위 값. 내가 시작하지 않은 콜백(CSRF)을 거르는 데 쓴다."""
    return secrets.token_urlsafe(32)
