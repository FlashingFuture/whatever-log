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


def test_today_endpoint_returns_json_with_cors_header(running_server) -> None:
    """apps/ui가 다른 오리진에서 fetch하므로 CORS 허용 헤더가 꼭 있어야 한다."""
    with urllib.request.urlopen(f"{running_server}/api/today", timeout=2) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        payload = json.loads(response.read())

    assert "date" in payload
    assert "total_seconds" in payload
    assert "by_process" in payload


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
