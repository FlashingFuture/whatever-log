import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer

import pytest
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick
from supervision.lock import acquire_lock

import hub.__main__ as hub_main
from hub.__main__ import EXIT_ALREADY_RUNNING, _Handler, _lock_path_for_port, main


@pytest.fixture
def running_server(tmp_path):
    """임시 DB를 가리키는 실제 HTTP 서버를 띄우고, 끝나면 정리한다."""
    db_path = tmp_path / "recorder.db"
    conn = open_db(db_path)
    save_tick(
        conn,
        TickSample(
            sampled_at=datetime.now(UTC),
            foreground_process="chrome.exe",
            windowed_processes=frozenset({"chrome.exe"}),
            seconds_since_last_input=0.0,
        ),
    )
    conn.close()

    _Handler.db_path = db_path
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_today_endpoint_reflects_allowed_localhost_origin(running_server) -> None:
    """apps/ui가 127.0.0.1의 다른 포트에서 fetch하므로, 그 origin은 허용해서
    돌려줘야 브라우저가 응답을 읽을 수 있다."""
    request = urllib.request.Request(
        f"{running_server}/api/today", headers={"Origin": "http://127.0.0.1:5173"}
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
        assert response.headers["Vary"] == "Origin"
        payload = json.loads(response.read())

    assert "date" in payload
    assert "total_seconds" in payload
    assert "by_process" in payload


def test_today_endpoint_does_not_allow_arbitrary_origins(running_server) -> None:
    """사용 기록(개인 활동 정보)이 들어 있는 응답을, 사용자가 띄워둔 아무
    웹사이트나 fetch해서 읽어가면 안 된다 — 허용되지 않은 origin에는 CORS
    헤더를 안 보내서 브라우저가 읽기를 막게 해야 한다."""
    request = urllib.request.Request(
        f"{running_server}/api/today", headers={"Origin": "http://evil.example"}
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert "Access-Control-Allow-Origin" not in response.headers


def test_today_endpoint_returns_503_when_db_is_missing(tmp_path) -> None:
    """DB 파일이 아직 없으면(recorder가 한 번도 안 돈 경우), 응답 없이 연결이
    끊기는 대신 503으로 알려야 한다."""
    _Handler.db_path = tmp_path / "missing.db"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/today", timeout=2)
        assert exc_info.value.code == 503
    finally:
        server.shutdown()


def test_unknown_path_returns_404(running_server) -> None:
    """정의되지 않은 경로는 404로 응답해야 한다(서버가 그냥 멈추면 안 됨)."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/unknown", timeout=2)

    assert exc_info.value.code == 404


def test_main_exits_with_already_running_code_when_lock_is_held(tmp_path, monkeypatch) -> None:
    """다른 hub가 이미 같은 포트의 lock을 잡고 있으면, 포트 바인딩을 시도하다가
    알기 어려운 에러로 죽는 대신 바로 EXIT_ALREADY_RUNNING으로 종료해야 한다."""
    port = 59123
    monkeypatch.setattr(sys, "argv", ["hub", "--port", str(port)])
    monkeypatch.setattr(hub_main, "DEFAULT_LOG_PATH", tmp_path / "hub.log")

    held_lock = acquire_lock(_lock_path_for_port(port))
    try:
        with pytest.raises(SystemExit) as exc_info:
            main()
    finally:
        held_lock.release()
        hub_main.logger.handlers.clear()

    assert exc_info.value.code == EXIT_ALREADY_RUNNING
