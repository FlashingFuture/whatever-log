from datetime import UTC, datetime

import keyring
import keyring.backend
import keyring.errors
import pytest

from cloud import KeyringTokenStore, Session


class _MemoryKeyring(keyring.backend.KeyringBackend):
    """실제 자격 증명 관리자를 건드리지 않는 테스트용 백엔드."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.items:
            raise keyring.errors.PasswordDeleteError("없음")
        del self.items[(service, username)]


@pytest.fixture
def backend():
    previous = keyring.get_keyring()
    backend = _MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


SESSION = Session("tok-123", datetime(2026, 12, 6, 3, 0, tzinfo=UTC), "a@example.com")


def test_a_session_round_trips(backend) -> None:
    store = KeyringTokenStore("svc", "user")

    store.save(SESSION)

    assert store.load() == SESSION


def test_nothing_stored_means_signed_out(backend) -> None:
    assert KeyringTokenStore("svc", "user").load() is None


def test_a_session_without_expiry_or_email_round_trips(backend) -> None:
    store = KeyringTokenStore("svc", "user")

    store.save(Session("tok"))

    assert store.load() == Session("tok", None, None)


def test_saving_replaces_the_previous_session(backend) -> None:
    store = KeyringTokenStore("svc", "user")
    store.save(SESSION)

    store.save(Session("tok-new"))

    assert store.load() == Session("tok-new")


def test_clear_removes_it_and_is_safe_when_empty(backend) -> None:
    store = KeyringTokenStore("svc", "user")
    store.save(SESSION)

    store.clear()
    store.clear()

    assert store.load() is None and backend.items == {}


@pytest.mark.parametrize(
    "raw", ["not json", "[]", "{}", '{"token": ""}', '{"token": 5}', '{"token": "t", "expires_at": "yesterday"}', "null"]
)
def test_a_corrupted_entry_reads_as_signed_out(backend, raw) -> None:
    backend.items[("svc", "user")] = raw

    assert KeyringTokenStore("svc", "user").load() is None


def test_an_unusable_credential_manager_reads_as_signed_out_but_save_reports_it() -> None:
    previous = keyring.get_keyring()
    from keyring.backends import fail

    keyring.set_keyring(fail.Keyring())
    try:
        store = KeyringTokenStore("svc", "user")
        assert store.load() is None  # 로컬 기능이 로그인에 의존하지 않게
        with pytest.raises(keyring.errors.KeyringError):
            store.save(SESSION)
    finally:
        keyring.set_keyring(previous)


def test_the_token_is_stored_only_in_the_credential_manager(backend) -> None:
    KeyringTokenStore("svc", "user").save(SESSION)

    assert "tok-123" in backend.items[("svc", "user")]
