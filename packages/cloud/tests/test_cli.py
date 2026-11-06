from datetime import UTC, datetime, timedelta

import pytest

import cloud.__main__ as cli
from cloud import Account, InMemoryTokenStore, LoginCancelled, LoginFailed, Session

NOW = datetime(2026, 11, 6, 3, 0, tzinfo=UTC)


def _account(session: Session | None = None) -> Account:
    store = InMemoryTokenStore()
    if session:
        store.save(session)
    return Account(store, now=lambda: NOW)


def test_status_reports_signed_out(capsys) -> None:
    assert cli.main(["status"], account=_account()) == 1
    assert "로그인되어 있지 않습니다" in capsys.readouterr().out


def test_status_shows_the_email_and_expiry_but_never_the_token(capsys) -> None:
    session = Session("secret-token-value", NOW + timedelta(days=30), "a@example.com")

    assert cli.main(["status"], account=_account(session)) == 0

    out = capsys.readouterr().out
    assert "a@example.com" in out and "2026-12-06" in out
    assert "secret-token-value" not in out


def test_logout_clears_the_session(capsys) -> None:
    account = _account(Session("tok"))

    assert cli.main(["logout"], account=account) == 0

    assert not account.is_signed_in()
    assert "로그아웃했습니다" in capsys.readouterr().out


def test_login_stores_the_session_on_success(monkeypatch, capsys) -> None:
    session = Session("tok", NOW + timedelta(days=30), "a@example.com")
    monkeypatch.setattr(cli, "sign_in_with_google", lambda config, **kwargs: session)
    account = _account()

    assert cli.main(["login"], account=account) == 0

    assert account.require_session() == session
    assert "a@example.com" in capsys.readouterr().out


@pytest.mark.parametrize("error", [LoginCancelled(), LoginFailed("서버에 연결하지 못했습니다.")])
def test_login_failures_keep_the_user_signed_out(monkeypatch, capsys, error) -> None:
    def fail(config, **kwargs):
        raise error

    monkeypatch.setattr(cli, "sign_in_with_google", fail)
    account = _account()

    assert cli.main(["login"], account=account) == 1

    assert not account.is_signed_in()
    assert str(error) in capsys.readouterr().out


def test_unknown_commands_are_rejected() -> None:
    with pytest.raises(SystemExit):
        cli.main(["delete-everything"], account=_account())
