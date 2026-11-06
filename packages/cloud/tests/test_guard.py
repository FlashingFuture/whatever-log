from datetime import UTC, datetime, timedelta

import pytest

from cloud import Account, InMemoryTokenStore, NotSignedIn, Session, require_login

NOW = datetime(2026, 11, 6, 3, 0, tzinfo=UTC)


class _ReportClient:
    """서버를 부르는 쪽의 모양: 로그인 상태를 아는 account와, 로그인을 요구하는 메서드."""

    def __init__(self, account: Account) -> None:
        self.account = account
        self.calls: list[tuple[str, str]] = []

    @require_login
    def send_report(self, session: Session, day: str) -> str:
        """서버로 가는 척하고 호출을 기록한다."""
        self.calls.append((session.token, day))
        return f"sent {day}"

    def local_summary(self) -> str:
        """로그인과 무관한 로컬 기능."""
        return "local ok"


def _client(session: Session | None = None) -> _ReportClient:
    store = InMemoryTokenStore()
    if session is not None:
        store.save(session)
    return _ReportClient(Account(store, now=lambda: NOW))


def test_signed_in_calls_run_and_receive_the_session() -> None:
    client = _client(Session("tok", NOW + timedelta(hours=1)))

    assert client.send_report("2026-11-05") == "sent 2026-11-05"
    assert client.calls == [("tok", "2026-11-05")]


def test_signed_out_calls_fail_before_the_body_runs() -> None:
    client = _client()

    with pytest.raises(NotSignedIn):
        client.send_report("2026-11-05")
    assert client.calls == []  # 본문(= 네트워크 호출)이 실행되지 않았다


def test_an_expired_session_is_rejected_too() -> None:
    client = _client(Session("tok", NOW - timedelta(seconds=1)))

    with pytest.raises(NotSignedIn):
        client.send_report("2026-11-05")
    assert client.calls == []


def test_local_features_do_not_need_a_login() -> None:
    assert _client().local_summary() == "local ok"


def test_the_decorator_keeps_the_function_metadata() -> None:
    assert _ReportClient.send_report.__name__ == "send_report"
    assert "서버로 가는 척" in (_ReportClient.send_report.__doc__ or "")


def test_keyword_arguments_pass_through() -> None:
    client = _client(Session("tok"))

    assert client.send_report(day="2026-11-04") == "sent 2026-11-04"
