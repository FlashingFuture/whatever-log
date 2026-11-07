from datetime import UTC, datetime, timedelta

import cloud
import keyring
import keyring.backend
import keyring.errors
import pytest

from hub.account_service import AccountService, LoginProblem, LogoutProblem
from hub.cloud_adapter import create_cloud_port

FUTURE = datetime.now(UTC) + timedelta(days=30)


class MemoryKeyring(keyring.backend.KeyringBackend):
    """실제 자격 증명 관리자를 건드리지 않는 테스트용 백엔드."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.fail_delete = False

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if self.fail_delete:
            raise keyring.errors.PasswordDeleteError("잠금")
        if (service, username) not in self.items:
            raise keyring.errors.PasswordDeleteError("없음")
        del self.items[(service, username)]


@pytest.fixture
def backend():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_providers_come_from_cloud(backend) -> None:
    port = create_cloud_port()

    assert [(item.id, item.label) for item in port.providers()] == [("google", "Google")]


def test_signed_out_until_a_session_is_stored(backend) -> None:
    port = create_cloud_port()
    assert port.current() is None

    backend.set_password("whatever.log", "session", '{"token": "t", "expires_at": null, "email": "a@example.com"}')

    assert port.current().email == "a@example.com"


def test_sign_in_stores_the_session_in_the_credential_manager_only(backend, monkeypatch) -> None:
    seen: dict = {}

    def fake_sign_in(provider_id, config, **options):
        seen.update(provider_id=provider_id, **options)
        return cloud.Session("secret-token", FUTURE, "a@example.com")

    monkeypatch.setattr(cloud, "sign_in", fake_sign_in)
    port = create_cloud_port()

    port.sign_in("google", cancelled=lambda: False)

    assert seen["provider_id"] == "google" and callable(seen["open_browser"]) and callable(seen["cancelled"])
    assert port.current().email == "a@example.com"
    assert "secret-token" in backend.items[("whatever.log", "session")]


def test_cancel_and_failure_are_mapped_to_login_problems(backend, monkeypatch) -> None:
    port = create_cloud_port()

    def cancelled(provider_id, config, **options):
        raise cloud.LoginCancelled

    monkeypatch.setattr(cloud, "sign_in", cancelled)
    with pytest.raises(LoginProblem) as raised:
        port.sign_in("google", cancelled=lambda: False)
    assert raised.value.cancelled is True

    def failed(provider_id, config, **options):
        raise cloud.LoginFailed("서버에 연결하지 못했습니다.")

    monkeypatch.setattr(cloud, "sign_in", failed)
    with pytest.raises(LoginProblem) as raised:
        port.sign_in("google", cancelled=lambda: False)
    assert raised.value.cancelled is False and "연결하지 못했습니다" in raised.value.message


def test_an_unusable_credential_manager_is_a_clear_login_failure(monkeypatch) -> None:
    from keyring.backends import fail

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        monkeypatch.setattr(cloud, "sign_in", lambda provider_id, config, **options: cloud.Session("t", FUTURE, "a@example.com"))
        port = create_cloud_port()

        with pytest.raises(LoginProblem, match="자격 증명 관리자"):
            port.sign_in("google", cancelled=lambda: False)
    finally:
        keyring.set_keyring(previous)


def test_sign_out_revokes_on_the_server_then_clears_locally(backend, monkeypatch) -> None:
    revoked: list[tuple[str, str]] = []
    monkeypatch.setattr(cloud, "revoke_session", lambda url, token: revoked.append((url, token)) or True)
    port = create_cloud_port()
    backend.set_password("whatever.log", "session", '{"token": "tok-1", "expires_at": null, "email": "a@example.com"}')

    assert port.sign_out() is True

    assert revoked == [(cloud.load_config().server_url, "tok-1")]
    assert port.current() is None and backend.items == {}


def test_sign_out_still_clears_locally_when_the_server_cannot_be_reached(backend, monkeypatch) -> None:
    monkeypatch.setattr(cloud, "revoke_session", lambda url, token: False)
    port = create_cloud_port()
    backend.set_password("whatever.log", "session", '{"token": "tok-1", "expires_at": null, "email": null}')

    assert port.sign_out() is False
    assert backend.items == {}


def test_sign_out_when_not_signed_in_does_not_call_the_server(backend, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(cloud, "revoke_session", lambda url, token: calls.append(token) or True)

    assert create_cloud_port().sign_out() is False
    assert calls == []


def test_a_local_delete_failure_is_reported_not_hidden(backend, monkeypatch) -> None:
    monkeypatch.setattr(cloud, "revoke_session", lambda url, token: True)
    port = create_cloud_port()
    backend.set_password("whatever.log", "session", '{"token": "tok-1", "expires_at": null, "email": null}')
    backend.fail_delete = True

    with pytest.raises(LogoutProblem):
        port.sign_out()


def test_the_service_over_the_real_adapter_never_exposes_the_token(backend, monkeypatch) -> None:
    monkeypatch.setattr(cloud, "sign_in", lambda provider_id, config, **options: cloud.Session("secret-token", FUTURE, "a@example.com"))
    service = AccountService(create_cloud_port)

    service.start_login("google")
    service.wait_for_login(5)

    snapshot = service.snapshot()
    assert snapshot["signed_in"] is True
    assert "secret-token" not in repr(snapshot)


def test_sign_out_clears_locally_even_when_the_server_address_setting_is_broken(backend, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_SERVER_URL", "ftp://broken")
    port = create_cloud_port()
    backend.set_password("whatever.log", "session", '{"token": "tok-1", "expires_at": null, "email": "a@example.com"}')

    assert port.sign_out() is False  # 서버 폐기는 못 했지만
    assert backend.items == {} and port.current() is None  # 이 PC에서는 로그아웃됐다


def test_sign_out_still_clears_locally_when_the_revoke_call_itself_blows_up(backend, monkeypatch) -> None:
    def boom(url, token):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(cloud, "revoke_session", boom)
    port = create_cloud_port()
    backend.set_password("whatever.log", "session", '{"token": "tok-1", "expires_at": null, "email": null}')

    assert port.sign_out() is False and backend.items == {}


def test_the_server_token_is_not_revoked_when_the_local_delete_failed(backend, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(cloud, "revoke_session", lambda url, token: calls.append(token) or True)
    port = create_cloud_port()
    backend.set_password("whatever.log", "session", '{"token": "tok-1", "expires_at": null, "email": null}')
    backend.fail_delete = True

    with pytest.raises(LogoutProblem):
        port.sign_out()

    assert calls == []  # 이 PC에는 로그인이 남아 있으니 토큰을 죽이지 않는다


def test_a_login_that_finishes_after_a_sign_out_is_not_saved_and_its_token_is_revoked(backend, monkeypatch) -> None:
    import threading

    revoked: list[str] = []
    monkeypatch.setattr(cloud, "revoke_session", lambda url, token: revoked.append(token) or True)
    exchanging = threading.Event()
    finish = threading.Event()

    def slow_sign_in(provider_id, config, **options):
        exchanging.set()  # 코드를 서버에 보내 토큰을 받는 중
        assert finish.wait(5)
        return cloud.Session("late-token", FUTURE, "a@example.com")

    monkeypatch.setattr(cloud, "sign_in", slow_sign_in)
    service = AccountService(create_cloud_port)
    service.start_login("google")
    assert exchanging.wait(5)

    service.sign_out()  # 교환 중에 로그아웃(= 로그인 취소)
    finish.set()
    service.wait_for_login(5)

    assert backend.items == {}  # 로그아웃 뒤에 로그인 정보가 되살아나지 않았다
    assert revoked == ["late-token"]  # 발급된 토큰은 서버에서 폐기를 시도했다
    snapshot = service.snapshot()
    assert snapshot["signed_in"] is False and snapshot["login"] == {"state": "idle", "message": None}


def test_a_login_cancelled_during_the_exchange_ends_as_a_cancel_even_if_revoking_fails(backend, monkeypatch) -> None:
    import threading

    def failing_revoke(url, token):
        raise OSError("down")

    monkeypatch.setattr(cloud, "revoke_session", failing_revoke)
    exchanging = threading.Event()
    finish = threading.Event()

    def slow_sign_in(provider_id, config, **options):
        exchanging.set()
        assert finish.wait(5)
        return cloud.Session("late-token", FUTURE, "a@example.com")

    monkeypatch.setattr(cloud, "sign_in", slow_sign_in)
    service = AccountService(create_cloud_port)
    service.start_login("google")
    assert exchanging.wait(5)
    service.cancel_login()
    finish.set()
    service.wait_for_login(5)

    snapshot = service.snapshot()
    assert backend.items == {} and snapshot["login"] == {"state": "idle", "message": None}
