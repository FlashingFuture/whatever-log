from datetime import UTC, datetime, timedelta

import pytest

from cloud import Account, InMemoryTokenStore, NotSignedIn, Session

NOW = datetime(2026, 11, 6, 3, 0, tzinfo=UTC)


def _account(store=None) -> Account:
    return Account(store or InMemoryTokenStore(), now=lambda: NOW)


def test_a_fresh_account_is_signed_out() -> None:
    account = _account()

    assert account.session() is None
    assert not account.is_signed_in()
    with pytest.raises(NotSignedIn):
        account.require_session()


def test_signing_in_stores_the_session_and_signing_out_clears_it() -> None:
    store = InMemoryTokenStore()
    account = _account(store)
    session = Session("tok", NOW + timedelta(days=1))

    account.sign_in(session)

    assert account.is_signed_in() and account.require_session() == session
    assert store.load() == session
    account.sign_out()
    assert not account.is_signed_in() and store.load() is None
    account.sign_out()  # 이미 로그아웃한 상태에서 또 해도 오류가 아니다


def test_an_expired_session_counts_as_signed_out_but_is_not_deleted() -> None:
    store = InMemoryTokenStore()
    expired = Session("tok", NOW)  # 만료 시각이 지금이면 이미 만료
    store.save(expired)

    account = _account(store)

    assert account.session() is None
    with pytest.raises(NotSignedIn):
        account.require_session()
    assert store.load() == expired  # 갱신을 붙일 때 쓸 수 있게 지우지 않는다


def test_a_session_without_expiry_never_expires() -> None:
    store = InMemoryTokenStore()
    store.save(Session("tok"))

    far_future = Account(store, now=lambda: NOW + timedelta(days=3650))

    assert far_future.is_signed_in()


def test_not_signed_in_has_a_user_facing_message() -> None:
    assert str(NotSignedIn()) == "로그인이 필요합니다."
