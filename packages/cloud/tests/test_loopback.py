import threading
import time
import urllib.error
import urllib.request

import pytest

from cloud.errors import LoginCancelled, LoginFailed
from cloud.loopback import LoopbackReceiver

STATE = "state-abc"


def _get(url: str) -> tuple[int, dict[str, str], str]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode("utf-8")


def _call_later(receiver: LoopbackReceiver, query: str, results: list, delay: float = 0.05) -> threading.Thread:
    def run() -> None:
        time.sleep(delay)
        results.append(_get(f"{receiver.redirect_uri}{query}"))

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_it_binds_to_the_loopback_address_only() -> None:
    with LoopbackReceiver(STATE) as receiver:
        assert receiver.redirect_uri.startswith("http://127.0.0.1:")
        assert receiver._server.server_address[0] == "127.0.0.1"
        assert receiver.redirect_uri.endswith("/callback")


def test_a_matching_callback_yields_the_code_and_a_friendly_page() -> None:
    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        thread = _call_later(receiver, f"?code=4%2F0AbcCode&state={STATE}", results)

        assert receiver.wait_for_code(timeout=5) == "4/0AbcCode"
        thread.join()

    status, headers, body = results[0]
    assert status == 200 and "로그인이 완료됐습니다" in body
    assert "4/0AbcCode" not in body  # 코드를 화면에 다시 보여 주지 않는다
    assert headers["Referrer-Policy"] == "no-referrer" and headers["Cache-Control"] == "no-store"


def test_callbacks_with_the_wrong_state_or_no_code_are_ignored_and_it_keeps_waiting() -> None:
    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        def attacker_then_user() -> None:
            time.sleep(0.05)
            results.append(_get(f"{receiver.redirect_uri}?code=evil&state=wrong"))
            results.append(_get(f"{receiver.redirect_uri}?code=evil"))
            results.append(_get(f"{receiver.redirect_uri}?state={STATE}"))  # 코드 없음
            results.append(_get(f"{receiver.redirect_uri}?code=good&state={STATE}"))

        thread = threading.Thread(target=attacker_then_user)
        thread.start()

        assert receiver.wait_for_code(timeout=5) == "good"
        thread.join()

    assert [status for status, _, _ in results] == [400, 400, 400, 200]


def test_other_paths_are_404_and_do_not_end_the_wait() -> None:
    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        def run() -> None:
            time.sleep(0.05)
            results.append(_get(receiver.redirect_uri.replace("/callback", "/favicon.ico")))
            results.append(_get(f"{receiver.redirect_uri}?code=ok&state={STATE}"))

        thread = threading.Thread(target=run)
        thread.start()

        assert receiver.wait_for_code(timeout=5) == "ok"
        thread.join()

    assert results[0][0] == 404


def test_the_user_cancelling_at_google_is_reported_as_cancelled() -> None:
    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        thread = _call_later(receiver, f"?error=access_denied&state={STATE}", results)

        with pytest.raises(LoginCancelled):
            receiver.wait_for_code(timeout=5)
        thread.join()

    assert results[0][0] == 200 and "취소" in results[0][2]


def test_an_error_callback_with_the_wrong_state_does_not_cancel_the_login() -> None:
    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        def run() -> None:
            time.sleep(0.05)
            results.append(_get(f"{receiver.redirect_uri}?error=access_denied&state=forged"))
            results.append(_get(f"{receiver.redirect_uri}?code=real&state={STATE}"))

        thread = threading.Thread(target=run)
        thread.start()

        assert receiver.wait_for_code(timeout=5) == "real"
        thread.join()


def test_waiting_times_out() -> None:
    with LoopbackReceiver(STATE) as receiver:
        started = time.monotonic()
        with pytest.raises(LoginFailed, match="시간이 지났습니다"):
            receiver.wait_for_code(timeout=0.5)
        assert time.monotonic() - started < 3


def test_the_port_is_released_after_the_with_block() -> None:
    with LoopbackReceiver(STATE) as receiver:
        uri = receiver.redirect_uri

    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(uri, timeout=1)


def test_an_oauth_error_other_than_cancelling_is_a_failure_not_a_cancel() -> None:
    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        thread = _call_later(receiver, f"?error=unauthorized_client&state={STATE}", results)

        with pytest.raises(LoginFailed, match="unauthorized_client") as raised:
            receiver.wait_for_code(timeout=5)
        thread.join()

    assert not isinstance(raised.value, LoginCancelled)
    assert "취소" not in results[0][2]


def test_an_error_code_with_odd_characters_is_not_echoed() -> None:
    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        thread = _call_later(receiver, f"?error=%3Cscript%3E&state={STATE}", results)

        with pytest.raises(LoginFailed) as raised:
            receiver.wait_for_code(timeout=5)
        thread.join()

    assert "script" not in str(raised.value) and "script" not in results[0][2]


def test_a_half_open_connection_does_not_block_the_real_callback_or_the_deadline() -> None:
    import socket

    results: list = []
    with LoopbackReceiver(STATE) as receiver:
        port = receiver._server.server_port
        stalled = socket.create_connection(("127.0.0.1", port))  # 요청을 보내지 않고 연결만 붙잡는다
        try:
            thread = _call_later(receiver, f"?code=real&state={STATE}", results)

            started = time.monotonic()
            assert receiver.wait_for_code(timeout=5) == "real"
            thread.join()
            assert time.monotonic() - started < 2
        finally:
            stalled.close()


def test_a_half_open_connection_does_not_push_past_the_deadline() -> None:
    import socket

    with LoopbackReceiver(STATE) as receiver:
        stalled = socket.create_connection(("127.0.0.1", receiver._server.server_port))
        try:
            started = time.monotonic()
            with pytest.raises(LoginFailed, match="시간이 지났습니다"):
                receiver.wait_for_code(timeout=0.5)
            assert time.monotonic() - started < 2
        finally:
            stalled.close()
