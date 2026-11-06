"""로그인을 직접 해 보는 명령줄: `uv run python -m cloud login | status | logout`.

화면(UI)의 로그인 버튼이 생기기 전에 흐름을 확인하는 용도이고, 화면도 같은 `Account`와 `sign_in_with_google`을 쓴다.
"""

import argparse
import sys

import keyring.errors
from datetime import UTC, datetime

from cloud.account import Account
from cloud.config import load_config
from cloud.errors import LoginCancelled, LoginFailed
from cloud.google_login import sign_in_with_google
from cloud.keyring_store import KeyringTokenStore


def _login(account: Account) -> int:
    """브라우저로 Google 로그인을 하고 세션을 자격 증명 관리자에 저장한다."""
    try:
        session = sign_in_with_google(
            load_config(),
            show_url=lambda url: print(
                f"브라우저가 열리지 않으면 이 주소를 직접 여세요:\n{url}\n", file=sys.stderr
            ),
        )
        account.sign_in(session)
    except LoginCancelled as error:
        print(error)
        return 1
    except keyring.errors.KeyringError as error:
        print(f"로그인 정보를 저장하지 못했습니다: {error}")
        return 1
    except LoginFailed as error:
        print(f"로그인하지 못했습니다: {error}")
        return 1
    print(f"로그인했습니다: {session.email or '(이메일 정보 없음)'}")
    return 0


def _status(account: Account) -> int:
    """로그인 상태를 알려 준다(토큰 값은 출력하지 않는다)."""
    session = account.session()
    if session is None:
        print("로그인되어 있지 않습니다.")
        return 1
    expires = session.expires_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if session.expires_at else "만료 없음"
    print(f"로그인됨: {session.email or '(이메일 정보 없음)'} (만료: {expires})")
    return 0


def main(argv: list[str] | None = None, *, account: Account | None = None, now: datetime | None = None) -> int:
    """명령을 실행하고 종료 코드(0 성공)를 돌려준다. account는 테스트용이다."""
    parser = argparse.ArgumentParser(prog="cloud", description="whatever.log 서버 로그인")
    parser.add_argument("command", choices=["login", "status", "logout"])
    args = parser.parse_args(argv)
    account = account or Account(KeyringTokenStore(), now=(lambda: now) if now else lambda: datetime.now(UTC))

    if args.command == "login":
        return _login(account)
    if args.command == "status":
        return _status(account)
    try:
        account.sign_out()
    except keyring.errors.KeyringError as error:
        print(f"로그인 정보를 지우지 못했습니다: {error}")
        return 1
    print("로그아웃했습니다. (이 PC의 로그인 정보만 지웠습니다. 서버에 남은 토큰은 만료 때까지 유효합니다.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
