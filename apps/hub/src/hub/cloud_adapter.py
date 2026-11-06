"""hub에서 `cloud` 패키지를 아는 유일한 파일.

`cloud` import는 반드시 함수 안에 둔다(`create_cloud_port`). 파일 맨 위에서 import하면 `cloud`(또는 그 의존성인
keyring)가 깨진 환경에서 hub 전체가 뜨지 않아, 기록·집계·목표까지 로그인 기능 때문에 멈추게 된다. 이 규칙은
packages/cloud/tests/test_isolation.py가 검사한다.
"""

import webbrowser
from collections.abc import Callable

from hub.account_service import (
    AccountUnavailable,
    CloudPort,
    Identity,
    LoginProblem,
    LogoutProblem,
    ProviderInfo,
)


def create_cloud_port() -> CloudPort:
    """`cloud`로 만든 CloudPort. `cloud`를 불러오지 못하면 AccountUnavailable."""
    try:
        import cloud  # 함수 안에서만 — 위 설명 참고
    except ImportError as error:
        raise AccountUnavailable from error
    return _CloudBackend(cloud)


class _CloudBackend:
    """CloudPort 구현. 토큰은 자격 증명 관리자에만 두고 밖으로 내보내지 않는다."""

    def __init__(self, cloud_module) -> None:
        """cloud 모듈을 받는다(import는 create_cloud_port에서만 한다)."""
        self._cloud = cloud_module
        self._account = cloud_module.Account(cloud_module.KeyringTokenStore())

    def providers(self) -> tuple[ProviderInfo, ...]:
        """cloud가 지원하는 로그인 방식들."""
        return tuple(ProviderInfo(item.id, item.label) for item in self._cloud.PROVIDERS.values())

    def current(self) -> Identity | None:
        """유효한 세션이 있으면 그 이메일."""
        session = self._account.session()
        return Identity(session.email) if session else None

    def sign_in(self, provider_id: str, *, cancelled: Callable[[], bool]) -> None:
        """시스템 브라우저로 로그인하고 세션을 저장한다."""
        cloud = self._cloud
        try:
            session = cloud.sign_in(
                provider_id, cloud.load_config(), open_browser=webbrowser.open, cancelled=cancelled
            )
            self._account.sign_in(session)
        except cloud.LoginCancelled as error:
            raise LoginProblem(str(error), cancelled=True) from None
        except cloud.LoginFailed as error:
            raise LoginProblem(str(error)) from None
        except cloud.StorageError:
            raise LoginProblem("이 PC의 안전한 저장소(Windows 자격 증명 관리자)를 쓸 수 없어 로그인 정보를 저장하지 못했습니다.") from None

    def sign_out(self) -> bool:
        """서버의 토큰 폐기를 시도하고(실패해도 계속), 이 PC의 로그인 정보를 지운다."""
        cloud = self._cloud
        revoked = False
        session = self._account.session()
        if session is not None:
            revoked = cloud.revoke_session(cloud.load_config().server_url, session.token)
        try:
            self._account.sign_out()
        except cloud.StorageError:
            raise LogoutProblem("이 PC의 로그인 정보를 지우지 못했습니다.") from None
        return revoked
