"""로그인 방식(제공자) 목록. 화면은 이 목록으로 로그인 버튼을 그리고, 새 방식을 붙일 때는 여기에 한 줄을 더한다.

지금은 Google 하나다(docs/auth-design.md). 새 방식은 `Provider`를 만들어 `PROVIDERS`에 넣고, 서버에는 그 방식의
코드 교환 주소(`/auth/<id>`)를 더하면 된다 — 화면과 hub는 이 목록만 보므로 바꿀 곳이 없다.
"""

from collections.abc import Callable
from dataclasses import dataclass

from cloud.config import CloudConfig
from cloud.google_login import sign_in_with_google
from cloud.server_client import Opener
from cloud.session import Session

SignIn = Callable[..., Session]


@dataclass(frozen=True)
class Provider:
    """로그인 방식 하나. id는 주소·요청에 쓰는 이름이고 label은 버튼에 보이는 이름이다."""

    id: str
    label: str
    sign_in: SignIn


PROVIDERS: dict[str, Provider] = {
    "google": Provider(id="google", label="Google", sign_in=sign_in_with_google),
}


def sign_in(
    provider_id: str,
    config: CloudConfig,
    *,
    show_url: Callable[[str], None] = lambda url: None,
    open_browser: Callable[[str], object] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    opener: Opener | None = None,
) -> Session:
    """고른 방식으로 로그인해 Session을 돌려준다. 모르는 방식이면 KeyError."""
    provider = PROVIDERS[provider_id]
    options: dict[str, object] = {"show_url": show_url, "cancelled": cancelled}
    if open_browser is not None:
        options["open_browser"] = open_browser
    if opener is not None:
        options["opener"] = opener
    return provider.sign_in(config, **options)
