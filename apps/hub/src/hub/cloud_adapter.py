"""hub에서 `cloud` 패키지를 아는 유일한 파일.

`cloud` import는 반드시 함수 안에 둔다(`create_cloud_port`). 파일 맨 위에서 import하면 `cloud`(또는 그 의존성인
keyring)가 깨진 환경에서 hub 전체가 뜨지 않아, 기록·집계·목표까지 로그인 기능 때문에 멈추게 된다. 이 규칙은
packages/cloud/tests/test_isolation.py가 검사한다.
"""

import hashlib
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


# 이 PC에서 계정 삭제를 보냈지만 결과를 알 수 없을 때 goals.db의 sync_meta에 남기는 표시(값은 그때의 세션 키). 그 세션이 나중에 서버에서
# 거부되면(401) 계정이 지워졌을 수 있으므로 동기화 연결을 정리하고, 화면은 "결과를 확인하지 못했다"를 계속 알린다.
META_DELETION_UNCERTAIN = "deletion_uncertain"


def session_key(token: str) -> str:
    """로그인(토큰)을 가리키는 불투명한 키. 토큰에 서비스 고유 문자열을 섞어 SHA-256으로 해시한 앞부분이라 토큰을 알아낼 수 없고(서버에 저장된 토큰
    해시와도 다르다), 같은 이메일로 다시 로그인하거나 이메일을 알 수 없는 다른 계정으로 바뀌어도 값이 달라진다."""
    return hashlib.sha256(b"whatever-log/session-key/" + token.encode("utf-8")).hexdigest()[:24]


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
        # 요청 처리 스레드마다 "이 요청이 쓴 토큰"을 기억한다. 401을 받았을 때 그 토큰의 세션만 지우기 위해서다(그 사이 로그아웃하고 다른
        # 계정으로 로그인했다면 새 계정의 자격 증명을 지우지 않는다).
        self._request = threading.local()

    def providers(self) -> tuple[ProviderInfo, ...]:
        """cloud가 지원하는 로그인 방식들."""
        return tuple(ProviderInfo(item.id, item.label) for item in self._cloud.PROVIDERS.values())

    def current(self) -> Identity | None:
        """유효한 세션이 있으면 그 이메일."""
        session = self._account.session()
        return Identity(session.email, session_key(session.token)) if session else None

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
        """로그인한 세션의 토큰으로 서버 API 클라이언트를 만든다. (api, 이메일, 세션 키)를 돌려준다. 로그인 전이면 SyncProblem."""
        cloud = self._cloud
        session = self._account.session()
        if session is None:
            raise SyncProblem("로그인이 필요합니다.", signed_out=True)
        try:
            server_url = cloud.load_config().server_url
        except ValueError:
            raise SyncProblem("서버 주소 설정이 올바르지 않습니다.") from None
        self._request.token = session.token  # 이 요청이 쓰는 토큰 — 401이 오면 이 토큰의 세션만 지운다
        return cloud.ServerApi(server_url, session.token), session.email, session_key(session.token)

    @staticmethod
    def _same_login(email: str | None, key: str, confirmed_email: str | None, confirmed_session: str | None) -> bool:
        """확인한 로그인(이메일·세션 키)이 지금 로그인과 같은가. 이메일만 비교하면 이메일을 알 수 없는 두 계정(None == None)이나 같은 이메일로 다시
        로그인한 경우를 구분하지 못한다."""
        return email == confirmed_email and key == confirmed_session

    def _forget_rejected_session(self, goals_db: Path | None) -> bool:
        """서버가 거부한 세션을 이 PC에서 지운다. **이 요청이 쓴 토큰의 세션일 때만** 지운다 — 그 사이 로그아웃하고 다른 계정으로 로그인했다면
        새 로그인은 건드리지 않는다(잠금 안에서 현재 토큰과 비교한다).

        이 세션에서 계정 삭제의 결과를 알 수 없었다면(deletion_uncertain), 서버가 토큰을 거부하는 것은 계정이 지워졌다는 신호일 수 있으므로
        목표의 서버 연결도 함께 정리한다(같은 이메일로 다시 가입해도 옛 연결이 남아 확인 창에서 빠지지 않게). 정리했으면 True.
        """
        token = getattr(self._request, "token", None)
        if token is None:
            return False
        with self._session_lock:
            current = self._account.session()
            if current is None or current.token != token:
                return False  # 이미 다른 세션이거나 로그아웃됐다
            try:
                self._account.sign_out()
            except self._cloud.StorageError:
                pass
        if goals_db is None:
            return False
        try:
            with _open_goals(goals_db) as store:
                if store.get_meta(META_DELETION_UNCERTAIN) == session_key(token):
                    store.reset_sync()  # 표시도 함께 지워진다(세대가 올라가 에이전트의 낡은 쓰기도 거절된다)
                    return True
        except Exception:
            pass
        return False

    def _guard(self, action, goals_db: Path | None = None):
        """서버 호출의 실패를 사용자용 SyncProblem으로 바꾼다(토큰·응답 내용은 담지 않는다)."""
        cloud = self._cloud
        try:
            return action()
        except cloud.NotAuthorized:
            # 서버가 이 토큰을 받지 않는다(만료 전에 폐기됐거나 서버에서 계정이 지워짐). 이 PC에 남겨 두면 로그인 상태로
            # 보이는데 아무것도 되지 않으므로 지워서 로그인 버튼이 보이게 한다.
            if self._forget_rejected_session(goals_db):
                raise SyncProblem(
                    "로그인이 만료되었습니다. 앞서 계정 삭제의 결과를 확인하지 못한 상태였어요. 다시 로그인한 뒤 서버의 목표 목록이 비어 있는지 "
                    "확인하거나, 계정 삭제를 다시 시도해 주세요.",
                    signed_out=True,
                ) from None
            raise SyncProblem("로그인이 만료되었습니다. 다시 로그인해 주세요.", signed_out=True) from None
        except cloud.ServerUnreachable:
            raise SyncProblem("서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.") from None
        except cloud.ServerError as error:
            raise SyncProblem(error.message) from None

    def sync_plan(self, goals_db: Path) -> dict[str, Any]:
        """서버의 목표 목록을 받아 이 PC의 목표와 견준 계획."""
        goalsync = self._goalsync

        def run():
            api, email, key = self._server()
            remote = api.list_goals()
            with _open_goals(goals_db) as store:
                return {**_plan_json(goalsync.build_plan(store, remote, email)), "session": key}

        return self._guard(run, goals_db)

    def sync_apply(
        self, goals_db: Path, accepted: Collection[str], confirmed_email: str | None, confirmed_session: str | None
    ) -> dict[str, Any]:
        """체크한 항목을 적용한다(서버 상태를 다시 읽어 계획을 새로 만든 뒤, 같은 key의 항목에 적용한다).

        confirmed_email·confirmed_session은 사용자가 확인 창에서 선택한 로그인이다. 그 사이 로그인이 바뀌었다면(다른 계정으로 다시
        로그인) 계정 A에서 고른 목표가 계정 B에 올라가거나 B의 목표와 합쳐질 수 있으므로 아무것도 하지 않고 다시 확인받는다.
        """
        goalsync = self._goalsync

        def run():
            api, email, key = self._server()
            if not self._same_login(email, key, confirmed_email, confirmed_session):
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

        return self._guard(run, goals_db)

    # --- 기기 목록과 계정 삭제 ---

    def _this_device_ids(self, goals_db: Path, sync_db: Path) -> set[str]:
        """이 PC의 기기일 수 있는 ID들. 에이전트가 `goals.db`(hub와 이미 공유하는 DB)에 알린 값과, 에이전트의 sync.db에 있는 값(읽기 전용)을 모두 모은다.

        두 값이 다를 수 있다(에이전트의 상태 DB를 바꾼 직후 — goals.db에는 옛 ID가, sync.db에는 새 ID가 있다). 어느 쪽이 지금 쓰는 ID인지 단정하지
        않고 **둘 다 이 PC의 기기로 본다** — 지우지 못하는 쪽으로 틀리는 것이 안전하다(현재 기기를 지우면 에이전트의 "이미 보냄" 기록 때문에 값이 바뀌기
        전에는 다시 올라오지 않는다).
        """
        found: set[str] = set()
        try:
            with _open_goals(goals_db) as store:
                published = store.get_meta("device_id")
            if published:
                found.add(published)
        except Exception:
            pass
        peeked = self._goalsync.peek_device_id(sync_db)
        if peeked:
            found.add(peeked)
        return found

    def list_devices(self, goals_db: Path, sync_db: Path) -> dict[str, Any]:
        """서버에 달성도를 보낸 기기들과 목록을 본 로그인. 이름은 없고 기기 ID·마지막으로 보낸 시각·줄 수뿐이며, 이 PC의 기기는 표시한다.

        email·session은 "이 목록은 이 로그인의 것"이라는 표시다 — 지우기 요청에 되돌려 보내, 그 사이 로그인이 바뀌면 거절하게 한다.
        """

        def run():
            api, email, key = self._server()
            mine = self._this_device_ids(goals_db, sync_db)
            return {
                "email": email,
                "session": key,
                "devices": [
                    {
                        "device_id": device.device_id,
                        "last_sent_at": device.last_sent_at,
                        "rows": device.rows,
                        "is_this_device": device.device_id in mine,
                    }
                    for device in api.list_devices()
                ],
            }

        return self._guard(run, goals_db)

    def delete_device(
        self, goals_db: Path, sync_db: Path, device_id: str, confirmed_email: str | None, confirmed_session: str | None
    ) -> None:
        """기기가 보낸 달성 기록을 서버에서 지운다.

        - 목록을 본 로그인(confirmed_email·confirmed_session)과 지금 로그인이 다르면 거절한다(계정 A의 목록에서 누른 삭제가 B의 기록을 지우지 않게).
        - 이 PC의 기기는 지우지 않는다(에이전트가 다음 주기에 다시 보낸다).
        - 이 PC의 기기를 확인할 수 없으면(에이전트가 아직 기기 ID를 알리지 않았다) 동기화를 켠 상태에서는 거절한다 — 모르는 채로 지우면
          이 PC의 기기를 지울 수 있고, 지운 줄은 에이전트의 "이미 보냄" 기록 때문에 변하지 않는 한 다시 올라오지 않는다.
        """

        def run():
            api, email, key = self._server()
            if not self._same_login(email, key, confirmed_email, confirmed_session):
                raise SyncProblem("로그인한 계정이 바뀌었어요. 기기 관리를 다시 열어 확인해 주세요.")
            mine = self._this_device_ids(goals_db, sync_db)
            if device_id in mine:
                raise SyncProblem("이 기기의 기록은 지울 수 없어요. 동기화 에이전트가 다음 주기에 다시 보내요. 동기화를 끄려면 로그아웃해 주세요.")
            if not mine and self._sync_enabled(goals_db):
                raise SyncProblem(
                    "이 기기가 어느 것인지 아직 확인하지 못했어요. 동기화 에이전트를 한 번 실행한 뒤 다시 시도해 주세요."
                )
            api.delete_device(device_id)

        self._guard(run, goals_db)

    @staticmethod
    def _sync_enabled(goals_db: Path) -> bool:
        """동기화를 켰는지(이 PC의 설정). 읽지 못하면 켠 것으로 본다 — 확인할 수 없을 때는 지우지 않는 쪽이 안전하다."""
        try:
            with _open_goals(goals_db) as store:
                return store.get_meta("sync_enabled") == "1"
        except Exception:
            return True

    def delete_account(self, goals_db: Path, confirmed_email: str | None, confirmed_session: str | None) -> dict[str, Any]:
        """서버의 계정과 모든 데이터를 지운다. 순서가 규칙이다: **서버 삭제가 성공한 뒤에만** 이 PC를 정리한다.

        서버 삭제가 실패하면 이 PC의 로그인·동기화 연결은 그대로 둔다(계정은 남아 있는데 이 PC만 로그아웃되어 지울 방법을 잃지 않게).
        성공한 뒤에는 이 PC의 로그인 정보를 지우고 목표의 서버 연결을 끊는다 — 목표와 프로세스 연결 자체는 이 PC에 그대로 남는다.
        확인한 로그인(이메일·세션 키)이 지금 로그인과 다르면 아무것도 하지 않는다. 이메일을 알 수 없는 로그인끼리는 이메일이 서로 같아
        보이므로(None) 세션 키로도 확인한다.

        요청을 보냈는데 응답을 받지 못했다면(연결 끊김·시간 초과) 서버가 이미 지웠을 수 있다. 그때는 "연결하지 못했다"가 아니라 "결과를 알 수
        없다"(`uncertain`)로 알리고, 이 PC는 그대로 두되 그 사실을 goals.db에 **표시**해 둔다(`deletion_uncertain`). 이후 같은 세션이 서버에서
        거부되면(계정이 지워졌을 수 있다) 그때 동기화 연결을 정리한다. "로그아웃되어 있으면 지워진 것"이라고 말하지 않는다 — 토큰이 만료·폐기돼도
        로그아웃으로 보이기 때문이다.
        """
        cloud = self._cloud

        def run():
            api, email, key = self._server()
            if not self._same_login(email, key, confirmed_email, confirmed_session):
                raise SyncProblem("로그인한 계정이 바뀌었어요. 계정 삭제를 다시 열어 확인해 주세요.")
            try:
                api.delete_account()
            except cloud.ServerUnreachable:
                self._mark_deletion_uncertain(goals_db, key)
                raise SyncProblem(
                    "서버에서 계정이 지워졌는지 확인하지 못했어요. 인터넷에 연결된 뒤 계정 삭제를 다시 시도해 주세요. 이미 지워졌다면 다시 시도할 때 "
                    "로그인이 필요하다고 안내돼요. (로그아웃되어 있다는 것만으로는 지워졌다고 볼 수 없어요.)",
                    uncertain=True,
                ) from None

        self._guard(run, goals_db)
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
                store.reset_sync()  # 동기화 세대가 올라가 진행 중이던 에이전트 주기의 낡은 쓰기는 거절된다(불확실 표시도 함께 지워진다)
        except Exception:
            connections_cleared = False
        return {"deleted_on_server": True, "signed_out": signed_out, "connections_cleared": connections_cleared}

    @staticmethod
    def _mark_deletion_uncertain(goals_db: Path, key: str) -> None:
        """삭제 결과를 알 수 없다는 표시를 남긴다(남기지 못해도 삭제 안내는 그대로 나간다)."""
        try:
            with _open_goals(goals_db) as store:
                store.set_meta(META_DELETION_UNCERTAIN, key)
        except Exception:
            pass


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
