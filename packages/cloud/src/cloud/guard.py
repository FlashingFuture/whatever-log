"""서버를 부르는 함수에 로그인을 요구하는 데코레이터."""

import functools
from collections.abc import Callable
from typing import Any, Concatenate, Protocol

from cloud.account import Account
from cloud.session import Session


class HasAccount(Protocol):
    """`@require_login`을 붙일 메서드의 객체가 가져야 하는 것: 로그인 상태를 아는 `account`."""

    account: Account


def require_login[Owner: HasAccount, **Params, Result](
    method: Callable[Concatenate[Owner, Session, Params], Result],
) -> Callable[Concatenate[Owner, Params], Result]:
    """서버를 부르는 메서드에 붙인다. 로그인이 안 되어 있거나 만료됐으면 **메서드 본문을 실행하기 전에**
    NotSignedIn을 던지고(네트워크에 가지 않는다), 되어 있으면 유효한 세션을 메서드의 첫 인자(self 다음)로
    넘겨 준다 — 메서드는 그 세션의 토큰으로 서버를 부르면 된다.

    로컬 기능(기록·집계·목표)에는 붙이지 않는다. 그쪽은 로그인 없이도 항상 동작해야 한다.
    """

    @functools.wraps(method)
    def wrapper(self: Owner, *args: Any, **kwargs: Any) -> Result:
        return method(self, self.account.require_session(), *args, **kwargs)

    return wrapper  # type: ignore[return-value]
