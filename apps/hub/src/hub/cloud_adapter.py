"""hub에서 `cloud` 패키지를 아는 유일한 파일.

`cloud` import는 반드시 함수 안에 둔다(`create_cloud_port`). 파일 맨 위에서 import하면 `cloud`(또는 그 의존성인
keyring)가 깨진 환경에서 hub 전체가 뜨지 않아, 기록·집계·목표까지 로그인 기능 때문에 멈추게 된다. 이 규칙은
packages/cloud/tests/test_isolation.py가 검사한다.
"""

import threading
import webbrowser
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any

from hub.account_service import (
    AccountUnavailable,
    CloudPort,
    Identity,
    LoginProblem,
    LogoutProblem,
    ProviderInfo,
    SyncProblem,
)


def create_cloud_port() -> CloudPort:
    """`cloud`로 만든 CloudPort. `cloud`를 불러오지 못하면 AccountUnavailable."""
    try:
        import cloud  # 함수 안에서만 — 위 설명 참고
        import goalsync
    except ImportError as error:
        raise AccountUnavailable from error
    return _CloudBackend(cloud, goalsync)


class _CloudBackend:
    """CloudPort 구현. 토큰은 자격 증명 관리자에만 두고 밖으로 내보내지 않는다."""

    def __init__(self, cloud_module, goalsync_module=None) -> None:
        """cloud·goalsync 모듈을 받는다(import는 create_cloud_port에서만 한다)."""
        self._cloud = cloud_module
        self._goalsync = goalsync_module
        self._account = cloud_module.Account(cloud_module.KeyringTokenStore())
        # 로그인 스레드가 세션을 저장하는 일과 로그아웃·만료 처리가 세션을 지우는 일을 한 번에 하나만 하게 한다.
        # 로그아웃이 지운 직후에 취소된 로그인이 뒤늦게 저장하는 일(로그아웃했는데 로그인 정보가 되살아남)을 막는다.
        self._session_lock = threading.Lock()

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
            config = cloud.load_config()
            session = cloud.sign_in(provider_id, config, open_browser=webbrowser.open, cancelled=cancelled)
            with self._session_lock:
                # 서버에서 토큰을 받는 사이에 취소·로그아웃이 일어났다면 저장하지 않는다. 취소는 로그아웃보다 먼저 표시되므로
                # (AccountService.sign_out), 이 확인과 저장이 잠금 안에서 함께 일어나면 로그아웃 뒤의 저장이 없다.
                if not cancelled():
                    self._account.sign_in(session)
                    return
            # 발급된 토큰은 쓰지 않으니 서버에서 폐기를 시도한다(실패해도 취소로 끝난다).
            self._revoke_quietly(config.server_url, session.token)
            raise LoginProblem("로그인을 취소했습니다.", cancelled=True)
        except cloud.LoginCancelled as error:
            raise LoginProblem(str(error), cancelled=True) from None
        except cloud.LoginFailed as error:
            raise LoginProblem(str(error)) from None
        except cloud.StorageError:
            raise LoginProblem("이 PC의 안전한 저장소(Windows 자격 증명 관리자)를 쓸 수 없어 로그인 정보를 저장하지 못했습니다.") from None
        except ValueError:  # 서버 주소 설정이 잘못됐다(환경 변수)
            raise LoginProblem("서버 주소 설정이 올바르지 않습니다.") from None

    def _revoke_quietly(self, server_url: str, token: str) -> bool:
        """서버의 토큰 폐기를 시도한다. 어떤 실패도 예외로 내보내지 않고 False를 돌려준다."""
        try:
            return bool(self._cloud.revoke_session(server_url, token))
        except Exception:
            return False

    def sign_out(self) -> bool:
        """서버의 토큰 폐기를 시도하고(실패해도 계속), 이 PC의 로그인 정보를 지운다."""
        cloud = self._cloud
        session = self._account.session()
        # 이 PC의 로그인 정보를 먼저 지운다(서버 설정이 잘못됐거나 서버가 죽어 있어도 로그아웃은 이 PC에서 끝나야 한다).
        # 지우지 못했다면 서버 토큰은 폐기하지 않는다 — 이 PC에는 로그인이 남아 있는데 토큰만 죽은 상태가 되지 않게.
        with self._session_lock:
            try:
                self._account.sign_out()
            except cloud.StorageError:
                raise LogoutProblem("이 PC의 로그인 정보를 지우지 못했습니다.") from None
        if session is None:
            return False
        try:
            server_url = cloud.load_config().server_url
        except ValueError:
            return False
        return self._revoke_quietly(server_url, session.token)

    # --- 목표 동기화 확인 창(docs/sync-client.md) ---

    def _server(self):
        """로그인한 세션의 토큰으로 서버 API 클라이언트를 만든다. 로그인 전이면 SyncProblem."""
        cloud = self._cloud
        session = self._account.session()
        if session is None:
            raise SyncProblem("로그인이 필요합니다.", signed_out=True)
        try:
            server_url = cloud.load_config().server_url
        except ValueError:
            raise SyncProblem("서버 주소 설정이 올바르지 않습니다.") from None
        return cloud.ServerApi(server_url, session.token), session.email

    def _forget_rejected_session(self) -> None:
        """서버가 거부한 세션을 이 PC에서 지운다(지우지 못해도 호출한 쪽의 오류 처리는 계속된다)."""
        with self._session_lock:
            try:
                self._account.sign_out()
            except self._cloud.StorageError:
                pass

    def _guard(self, action):
        """서버 호출의 실패를 사용자용 SyncProblem으로 바꾼다(토큰·응답 내용은 담지 않는다)."""
        cloud = self._cloud
        try:
            return action()
        except cloud.NotAuthorized:
            # 서버가 이 토큰을 받지 않는다(만료 전에 폐기됐거나 서버에서 계정이 지워짐). 이 PC에 남겨 두면 로그인 상태로
            # 보이는데 아무것도 되지 않으므로 지워서 로그인 버튼이 보이게 한다.
            self._forget_rejected_session()
            raise SyncProblem("로그인이 만료되었습니다. 다시 로그인해 주세요.", signed_out=True) from None
        except cloud.ServerUnreachable:
            raise SyncProblem("서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.") from None
        except cloud.ServerError as error:
            raise SyncProblem(error.message) from None

    def sync_plan(self, goals_db: Path) -> dict[str, Any]:
        """서버의 목표 목록을 받아 이 PC의 목표와 견준 계획."""
        goalsync = self._goalsync

        def run():
            api, email = self._server()
            remote = api.list_goals()
            with _open_goals(goals_db) as store:
                return _plan_json(goalsync.build_plan(store, remote, email))

        return self._guard(run)

    def sync_apply(self, goals_db: Path, accepted: Collection[str], confirmed_email: str | None) -> dict[str, Any]:
        """체크한 항목을 적용한다(서버 상태를 다시 읽어 계획을 새로 만든 뒤, 같은 key의 항목에 적용한다).

        confirmed_email은 사용자가 확인 창에서 선택한 계정이다. 그 사이 로그인한 계정이 바뀌었다면(다른 계정으로 다시
        로그인) 계정 A에서 고른 목표가 계정 B에 올라가거나 B의 목표와 합쳐질 수 있으므로 아무것도 하지 않고 다시 확인받는다.
        """
        goalsync = self._goalsync

        def run():
            api, email = self._server()
            if email != confirmed_email:
                raise SyncProblem("로그인한 계정이 바뀌었어요. 목표 동기화를 다시 열어 확인해 주세요.")
            with _open_goals(goals_db) as store:
                plan = goalsync.build_plan(store, api.list_goals(), email)
                result = goalsync.apply_choices(store, api, plan, set(accepted))
            return {
                "uploaded": result.uploaded,
                "merged": result.merged,
                "downloaded": result.downloaded,
                "kept_local": result.kept_local,
                "errors": [{"key": key, "message": message} for key, message in result.errors],
            }

        return self._guard(run)

    # --- 기기 목록과 계정 삭제 ---

    def _this_device_id(self, goals_db: Path, sync_db: Path) -> str | None:
        """이 PC의 기기 ID. 에이전트가 `goals.db`(hub와 이미 공유하는 DB)에 적어 둔 값을 먼저 보고, 없으면 에이전트의 sync.db를 읽기 전용으로 본다.

        hub의 `--sync-db-path`와 에이전트의 `--state-db`가 어긋나 있어도 goals.db는 같으므로 이 기기를 알아볼 수 있다.
        """
        try:
            with _open_goals(goals_db) as store:
                published = store.get_meta("device_id")
        except Exception:
            published = None
        return published or self._goalsync.peek_device_id(sync_db)

    def list_devices(self, goals_db: Path, sync_db: Path) -> dict[str, Any]:
        """서버에 달성도를 보낸 기기들과 목록을 본 계정. 이름은 없고 기기 ID·마지막으로 보낸 시각·줄 수뿐이며, 이 PC의 기기는 표시한다.

        email은 "이 목록은 이 계정의 것"이라는 표시다 — 지우기 요청에 되돌려 보내, 그 사이 계정이 바뀌면 거절하게 한다.
        """

        def run():
            api, email = self._server()
            mine = self._this_device_id(goals_db, sync_db)
            return {
                "email": email,
                "devices": [
                    {
                        "device_id": device.device_id,
                        "last_sent_at": device.last_sent_at,
                        "rows": device.rows,
                        "is_this_device": device.device_id == mine,
                    }
                    for device in api.list_devices()
                ],
            }

        return self._guard(run)

    def delete_device(self, goals_db: Path, sync_db: Path, device_id: str, confirmed_email: str | None) -> None:
        """기기가 보낸 달성 기록을 서버에서 지운다.

        - 목록을 본 계정(confirmed_email)과 지금 로그인한 계정이 다르면 거절한다(계정 A의 목록에서 누른 삭제가 B의 기록을 지우지 않게).
        - 이 PC의 기기는 지우지 않는다(에이전트가 다음 주기에 다시 보낸다).
        - 이 PC의 기기를 확인할 수 없으면(에이전트가 아직 기기 ID를 알리지 않았다) 동기화를 켠 상태에서는 거절한다 — 모르는 채로 지우면
          이 PC의 기기를 지울 수 있고, 지운 줄은 에이전트의 "이미 보냄" 기록 때문에 변하지 않는 한 다시 올라오지 않는다.
        """

        def run():
            api, email = self._server()
            if email != confirmed_email:
                raise SyncProblem("로그인한 계정이 바뀌었어요. 기기 관리를 다시 열어 확인해 주세요.")
            mine = self._this_device_id(goals_db, sync_db)
            if mine is not None and device_id == mine:
                raise SyncProblem("이 기기의 기록은 지울 수 없어요. 동기화 에이전트가 다음 주기에 다시 보내요. 동기화를 끄려면 로그아웃해 주세요.")
            if mine is None and self._sync_enabled(goals_db):
                raise SyncProblem(
                    "이 기기가 어느 것인지 아직 확인하지 못했어요. 동기화 에이전트를 한 번 실행한 뒤 다시 시도해 주세요."
                )
            api.delete_device(device_id)

        self._guard(run)

    @staticmethod
    def _sync_enabled(goals_db: Path) -> bool:
        """동기화를 켰는지(이 PC의 설정). 읽지 못하면 켠 것으로 본다 — 확인할 수 없을 때는 지우지 않는 쪽이 안전하다."""
        try:
            with _open_goals(goals_db) as store:
                return store.get_meta("sync_enabled") == "1"
        except Exception:
            return True

    def delete_account(self, goals_db: Path, confirmed_email: str | None) -> dict[str, Any]:
        """서버의 계정과 모든 데이터를 지운다. 순서가 규칙이다: **서버 삭제가 성공한 뒤에만** 이 PC를 정리한다.

        서버 삭제가 실패하면 이 PC의 로그인·동기화 연결은 그대로 둔다(계정은 남아 있는데 이 PC만 로그아웃되어 지울 방법을 잃지 않게).
        성공한 뒤에는 이 PC의 로그인 정보를 지우고 목표의 서버 연결을 끊는다 — 목표와 프로세스 연결 자체는 이 PC에 그대로 남는다.
        확인한 계정(confirmed_email)이 지금 로그인한 계정과 다르면 아무것도 하지 않는다.

        요청을 보냈는데 응답을 받지 못했다면(연결 끊김·시간 초과) 서버가 이미 지웠을 수 있다. 그때는 "연결하지 못했다"가 아니라 "결과를 알 수
        없다"(`uncertain`)로 알리고 이 PC는 그대로 둔다 — 다음에 서버를 부를 때 토큰이 거부되면(계정이 지워졌다는 뜻) 그때 정리된다.
        """
        cloud = self._cloud

        def run():
            api, email = self._server()
            if email != confirmed_email:
                raise SyncProblem("로그인한 계정이 바뀌었어요. 계정 삭제를 다시 열어 확인해 주세요.")
            try:
                api.delete_account()
            except cloud.ServerUnreachable:
                raise SyncProblem(
                    "서버에서 계정이 지워졌는지 확인하지 못했어요. 잠시 뒤 상단 막대에서 로그인 상태를 확인해 주세요. "
                    "로그아웃되어 있으면 계정이 지워진 거예요.",
                    uncertain=True,
                ) from None

        self._guard(run)
        # 여기부터는 서버에서 이미 지워졌다. 이 PC의 정리가 일부 실패해도 서버 삭제를 되돌릴 수 없으니, 무엇이 남았는지 알린다.
        signed_out = True
        with self._session_lock:
            try:
                self._account.sign_out()
            except cloud.StorageError:
                signed_out = False
        connections_cleared = True
        try:
            with _open_goals(goals_db) as store:
                store.reset_sync()  # 동기화 세대가 올라가 진행 중이던 에이전트 주기의 낡은 쓰기는 거절된다
        except Exception:
            connections_cleared = False
        return {"deleted_on_server": True, "signed_out": signed_out, "connections_cleared": connections_cleared}


def _open_goals(path: Path):
    """goals.db를 연다(함수 안에서 import — 맨 위에서 하면 이 파일이 goals까지 끌어온다는 오해를 부르지만, goals는 로컬 기능이라 무방하다)."""
    from goals import GoalStore

    return GoalStore(path)


def _plan_json(plan) -> dict[str, Any]:
    """계획을 화면용 JSON으로. 올라가는 값(이름·목표 시간·요일)만 담고, 프로세스·사이트·내부 id는 담지 않는다."""
    return {
        "email": plan.email,
        "enabled": plan.enabled,
        "items": [
            {
                "key": item.key,
                "kind": item.kind,
                "name": item.name,
                "daily_target_minutes": item.daily_target_minutes,
                "weekdays": list(item.weekdays),
                "local_daily_target_minutes": item.local_daily_target_minutes,
                "local_weekdays": None if item.local_weekdays is None else list(item.local_weekdays),
                "declined": item.declined,
            }
            for item in plan.items
        ],
    }
