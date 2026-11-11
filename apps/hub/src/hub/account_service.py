"""로그인 상태와 로그인 진행을 관리하는 서비스(`/api/account*`의 HTTP와 무관한 부분).

화면(UI)이 로그인 버튼을 그리려면 "로그인했는가, 누구인가, 로그인 중인가, 어떤 방식이 있는가"를 알아야 한다. 이
서비스가 그것을 한곳에서 답하고, 로그인은 별도 스레드에서 진행한다(브라우저에서 사용자가 끝낼 때까지 최대 3분이
걸려서 HTTP 요청을 붙잡아 둘 수 없다). 화면은 진행 중일 때만 주기적으로 상태를 물어 결과를 받는다.

이 서비스는 `cloud` 패키지를 직접 import하지 않는다 — `CloudPort`(아래)만 안다. 진짜 구현은 `hub.cloud_adapter`
한 파일에만 있고, `cloud`를 쓸 수 없는 환경이면 어댑터를 못 만들어서 계정 기능만 "사용할 수 없음"이 된다.
기록·집계·목표는 이 서비스와 무관하게 항상 동작한다(docs/auth-design.md의 "로컬 기능은 로그인과 무관").

토큰은 이 서비스를 지나가지 않는다: 어댑터가 자격 증명 관리자에 직접 저장하고, 화면에는 이메일만 나간다.
"""

import logging
import threading
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("hub.account")


class LoginProblem(Exception):
    """로그인이 끝나지 못했다. message는 사용자에게 그대로 보여 줄 수 있는 문장이고, cancelled면 사용자의 선택이다."""

    def __init__(self, message: str, *, cancelled: bool = False) -> None:
        """사용자용 메시지와 취소 여부를 담는다."""
        super().__init__(message)
        self.message = message
        self.cancelled = cancelled


class LogoutProblem(Exception):
    """이 PC의 로그인 정보를 지우지 못했다. message는 사용자에게 보여 줄 수 있다."""

    def __init__(self, message: str) -> None:
        """사용자용 메시지를 담는다."""
        super().__init__(message)
        self.message = message


class UnknownProvider(Exception):
    """없는 로그인 방식."""


class LoginInProgress(Exception):
    """이미 로그인이 진행 중이다."""


class AccountUnavailable(Exception):
    """계정 기능을 쓸 수 없다(`cloud`를 불러오지 못한 환경)."""


class SyncProblem(Exception):
    """동기화 확인 창의 요청을 처리하지 못했다. message는 사용자에게 그대로 보여 줄 수 있는 문장이고, signed_out이면 로그인이
    필요한 상황(로그인 전·만료)이다."""

    def __init__(self, message: str, *, signed_out: bool = False, uncertain: bool = False) -> None:
        """사용자용 메시지와 로그인 필요 여부를 담는다. uncertain은 요청이 서버에 닿았는지(처리됐는지) 알 수 없다는 뜻이다."""
        super().__init__(message)
        self.message = message
        self.signed_out = signed_out
        self.uncertain = uncertain


class SyncBusy(Exception):
    """이미 다른 동기화 적용이 진행 중이다."""


@dataclass(frozen=True)
class ProviderInfo:
    """화면의 로그인 버튼 하나: 요청에 쓰는 id와 버튼에 보이는 이름."""

    id: str
    label: str


@dataclass(frozen=True)
class Identity:
    """지금 로그인한 사람. 화면에 보이는 것은 이메일과 세션 키뿐이다(토큰은 어디에도 나가지 않는다).

    session은 이 로그인(토큰)을 가리키는 불투명한 키다 — 토큰의 salt 친 해시의 앞부분이라 토큰을 알아낼 수 없다. 화면이 "이 계정에서
    확인했다"는 표시로 되돌려 보내면, hub가 그 사이 로그인이 바뀌었는지 알아본다. 이메일은 같은 사람이 다시 로그인해도, 이메일을 알 수
    없는 두 계정(None)이어도 구분하지 못하지만 세션 키는 로그인마다 다르다.
    """

    email: str | None
    session: str | None = None


class CloudPort(Protocol):
    """서비스가 서버 쪽 기능에 바라는 것. 진짜 구현은 `hub.cloud_adapter`, 테스트는 가짜를 넣는다."""

    def providers(self) -> tuple[ProviderInfo, ...]:
        """쓸 수 있는 로그인 방식들."""
        ...

    def current(self) -> Identity | None:
        """유효한 로그인 정보. 로그인 안 됐거나 만료됐으면 None."""
        ...

    def sign_in(self, provider_id: str, *, cancelled: Callable[[], bool]) -> None:
        """고른 방식으로 로그인해 자격 증명 관리자에 저장한다. 실패·취소는 LoginProblem."""
        ...

    def sign_out(self) -> bool:
        """이 PC의 로그인 정보를 지우고, 서버의 토큰도 폐기를 시도한다(서버 폐기 성공 여부를 돌려준다). 지우지 못하면 LogoutProblem."""
        ...

    def sync_plan(self, goals_db: Path) -> dict[str, Any]:
        """로그인 직후 확인 창의 계획(서버 목표와 이 PC 목표를 견준 것). 서버·로그인 문제는 SyncProblem."""
        ...

    def sync_apply(
        self, goals_db: Path, accepted: Collection[str], email: str | None, session: str | None
    ) -> dict[str, Any]:
        """사용자가 체크한 항목(key)을 적용한다. email·session은 확인 창을 열었을 때의 로그인이고, 지금 로그인과 다르면 적용하지
        않고 SyncProblem을 올린다. 서버·로그인 문제도 SyncProblem."""
        ...

    def goal_totals(self, goals_db: Path, start_day: str, end_day: str) -> dict[str, Any]:
        """목표별 모든 기기의 합계(분). 다른 기기의 기록을 받을 수 없는 상태(로그인 전·동기화 꺼짐)면 `state: "local"`. 서버·로그인 문제는 SyncProblem."""
        ...

    def list_devices(self, goals_db: Path, sync_db: Path) -> dict[str, Any]:
        """달성도를 보낸 기기들과, 목록을 본 계정(`email`). 각 기기에 이 PC의 기기인지(`is_this_device`)를 표시한다. 서버·로그인 문제는 SyncProblem."""
        ...

    def delete_device(
        self, goals_db: Path, sync_db: Path, device_id: str, email: str | None, session: str | None
    ) -> None:
        """기기가 보낸 달성 기록을 서버에서 지운다. email·session(목록을 본 로그인)이 지금 로그인과 다르면, 이 PC의 기기이거나 이 PC의
        기기인지 확인할 수 없으면 SyncProblem — 아무것도 지우지 않는다."""
        ...

    def delete_account(self, goals_db: Path, email: str | None, session: str | None) -> dict[str, Any]:
        """서버의 계정과 데이터를 지우고, 성공한 뒤에만 이 PC의 로그인·동기화 연결을 정리한다. email·session(확인한 로그인)이 지금
        로그인과 다르면 아무것도 하지 않고 SyncProblem. 서버에서 지우지 못했다면 이 PC는 건드리지 않는다."""
        ...


class AccountService:
    """로그인 진행 상태(없음/진행 중/실패)를 들고, 요청에 맞춰 CloudPort를 부른다.

    `port_factory`는 처음 필요할 때 한 번 CloudPort를 만든다. 만들지 못하면(AccountUnavailable) 그 뒤로도 상태 조회는
    "available: false"로 답하고 다른 동작은 AccountUnavailable을 올린다 — hub의 다른 API에는 영향이 없다.
    """

    def __init__(self, port_factory: Callable[[], CloudPort]) -> None:
        """포트를 만드는 함수를 받는다(바로 부르지 않는다 — hub가 뜨는 데 `cloud`가 필요하지 않게)."""
        self._factory = port_factory
        self._port: CloudPort | None = None
        self._unavailable = False
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._sync_lock = threading.Lock()
        self._deleting = False
        self._thread: threading.Thread | None = None
        self._state = "idle"  # idle | pending | failed
        self._message: str | None = None
        # 이 hub가 지금의 로그인을 알게 된 시각: 로그인을 마친 때, 그 전부터 로그인되어 있었다면 hub가 뜬 때(이 객체를 만든 때).
        self._signed_in_since = datetime.now(UTC)

    def _get_port(self) -> CloudPort:
        """포트를 (처음이면 만들어) 돌려준다. 만들 수 없으면 AccountUnavailable."""
        with self._lock:
            if self._port is None and not self._unavailable:
                try:
                    self._port = self._factory()
                except AccountUnavailable:
                    self._unavailable = True
                except Exception:
                    logger.exception("계정 기능을 불러오지 못했습니다.")
                    self._unavailable = True
            if self._port is None:
                raise AccountUnavailable
            return self._port

    def snapshot(self) -> dict[str, Any]:
        """화면이 그릴 현재 상태. 토큰은 들어 있지 않다."""
        try:
            port = self._get_port()
        except AccountUnavailable:
            return {
                "available": False,
                "signed_in": False,
                "email": None,
                "session": None,
                "login": {"state": "idle", "message": None},
                "providers": [],
            }
        identity = port.current()
        with self._lock:
            login = {"state": self._state, "message": self._message}
        return {
            "available": True,
            "signed_in": identity is not None,
            "email": identity.email if identity else None,
            "session": identity.session if identity else None,
            "login": login,
            "providers": [{"id": item.id, "label": item.label} for item in port.providers()],
        }

    def start_login(self, provider_id: str) -> None:
        """로그인을 시작한다(스레드에서 진행). 모르는 방식이면 UnknownProvider, 이미 진행 중이면 LoginInProgress."""
        port = self._get_port()
        if provider_id not in {item.id for item in port.providers()}:
            raise UnknownProvider(provider_id)
        with self._lock:
            if self._deleting:
                # 계정을 지우는 동안에는 새 로그인을 시작하지 않는다 — 삭제 뒤의 정리가 방금 끝난 새 로그인의 세션을 지우게 된다.
                raise SyncBusy
            if self._state == "pending":
                raise LoginInProgress
            if self._thread is not None and self._thread.is_alive():
                # 취소했지만 아직 끝나지 않은 이전 로그인(서버와 코드를 교환하는 중일 수 있다)이 있다. 그 스레드를 놓치면 삭제가 그것을
                # 기다리지 못해, 삭제 뒤에 끝난 교환이 계정을 다시 만든다 — 끝날 때까지 새 로그인을 받지 않는다.
                raise SyncBusy
            self._state = "pending"
            self._message = None
            self._cancel = cancel = threading.Event()
            self._thread = threading.Thread(
                target=self._run_login, args=(port, provider_id, cancel), daemon=True, name="hub-login"
            )
            thread = self._thread
        thread.start()

    def _run_login(self, port: CloudPort, provider_id: str, cancel: threading.Event) -> None:
        """로그인 스레드. 결과를 상태에 적는다."""
        state, message = "idle", None
        try:
            port.sign_in(provider_id, cancelled=cancel.is_set)
            with self._lock:
                self._signed_in_since = datetime.now(UTC)
        except LoginProblem as problem:
            if not problem.cancelled:
                state, message = "failed", problem.message
        except Exception:
            logger.exception("로그인 중 예상하지 못한 오류가 났습니다.")
            state, message = "failed", "로그인하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
        with self._lock:
            if self._cancel is cancel:  # 그 사이 새 로그인이 시작됐다면 그 쪽 상태를 건드리지 않는다
                self._state, self._message = state, message

    def signed_in_since(self) -> datetime:
        """이 hub가 지금의 로그인을 알게 된 시각. 동기화 에이전트의 "로그인 안 됨" 기록이 이보다 앞서면 로그인 전 주기의
        기록이라 오류로 보지 않는다(로그인 직후 다음 주기까지 오류가 보이지 않게)."""
        with self._lock:
            return self._signed_in_since

    def cancel_login(self) -> None:
        """진행 중인 로그인을 취소한다(없으면 아무 일도 없다). 스레드가 곧 끝나면서 상태가 idle로 돌아온다."""
        with self._lock:
            self._cancel.set()

    def sign_out(self) -> bool:
        """로그아웃한다. 진행 중인 로그인이 있으면 취소한다. 서버 쪽 폐기까지 됐는지 돌려준다."""
        port = self._get_port()
        self.cancel_login()
        revoked = port.sign_out()
        with self._lock:
            self._state, self._message = "idle", None
        return revoked

    def sync_plan(self, goals_db: Path) -> dict[str, Any]:
        """동기화 확인 창에 보여 줄 계획. 계정 기능이 없으면 AccountUnavailable, 서버·로그인 문제는 SyncProblem."""
        return self._get_port().sync_plan(goals_db)

    def sync_apply(
        self, goals_db: Path, accepted: Collection[str], email: str | None, session: str | None
    ) -> dict[str, Any]:
        """체크한 항목을 적용한다. 같은 시각에 두 번 적용되지 않게 막는다(진행 중이면 SyncBusy)."""
        port = self._get_port()
        if not self._sync_lock.acquire(blocking=False):
            raise SyncBusy
        try:
            return port.sync_apply(goals_db, accepted, email, session)
        finally:
            self._sync_lock.release()

    def goal_totals(self, goals_db: Path, start_day: str, end_day: str) -> dict[str, Any]:
        """목표별 모든 기기의 합계. 계정 기능이 없으면 AccountUnavailable(호출부가 "이 PC의 값만"으로 처리한다)."""
        return self._get_port().goal_totals(goals_db, start_day, end_day)

    def list_devices(self, goals_db: Path, sync_db: Path) -> dict[str, Any]:
        """기기 목록(서버). 계정 기능이 없으면 AccountUnavailable."""
        return self._get_port().list_devices(goals_db, sync_db)

    def delete_device(
        self, goals_db: Path, sync_db: Path, device_id: str, email: str | None, session: str | None
    ) -> None:
        """기기 삭제(서버). 목록을 본 로그인(email·session)과 지금 로그인이 같을 때만 한다."""
        self._get_port().delete_device(goals_db, sync_db, device_id, email, session)

    def delete_account(self, goals_db: Path, email: str | None, session: str | None) -> dict[str, Any]:
        """계정 삭제. 진행 중인 로그인은 먼저 취소하고 완전히 끝나기를 기다린 뒤에만 서버를 부른다(동기화 적용과는 동시에 하지 않는다).

        기다리는 이유: 서버에서 코드를 교환하는 중인 로그인이 삭제 뒤에 끝나면 서버가 그 이메일 계정을 다시 만든다(토큰을 폐기해도 계정은
        남는다). 교환이 끝났음을 확인하지 못하면(시간 안에 끝나지 않음) 삭제하지 않고 SyncBusy로 돌려보낸다.
        """
        port = self._get_port()
        if not self._sync_lock.acquire(blocking=False):
            raise SyncBusy
        try:
            with self._lock:
                self._deleting = True  # 새 로그인 시작을 막는다(start_login)
            self.cancel_login()
            if not self._wait_for_login_to_finish():
                raise SyncBusy
            return port.delete_account(goals_db, email, session)
        finally:
            # 로그인 상태 표시를 먼저 되돌리고 같은 잠금 안에서 삭제 가드를 푼다 — 가드가 풀린 직후 시작된 새 로그인의 "진행 중"을
            # 이 정리가 idle로 덮어쓰지 않게 한다.
            with self._lock:
                if self._thread is None or not self._thread.is_alive():
                    self._state, self._message = "idle", None
                # 끝나지 않은 로그인이 남아 있으면 그 스레드가 끝나면서 상태를 정한다(여기서 idle로 보이게 하지 않는다)
                self._deleting = False
            self._sync_lock.release()

    #: 취소한 로그인이 끝나기를 기다리는 최대 시간(초). 코드 교환의 제한 시간(20초)과 토큰 폐기(5초)를 합친 것보다 길게 둔다.
    LOGIN_WRAP_UP_SECONDS = 30.0

    def _wait_for_login_to_finish(self) -> bool:
        """취소한 로그인 스레드가 끝나기를 기다린다. 끝났으면(또는 없으면) True, 시간 안에 끝나지 않았으면 False."""
        thread = self._thread
        if thread is None or thread is threading.current_thread() or not thread.is_alive():
            return True
        thread.join(self.LOGIN_WRAP_UP_SECONDS)
        return not thread.is_alive()

    def wait_for_login(self, timeout: float) -> None:
        """진행 중인 로그인 스레드가 끝나기를 기다린다(테스트용)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
