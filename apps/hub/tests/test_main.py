import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

import pytest
from recorder.sampling import TickSample
from recorder.storage import open_db, save_process_paths, save_tick
from supervision.lock import acquire_lock

import hub.__main__ as hub_main
from common.exit_codes import EXIT_ALREADY_RUNNING
from hub.__main__ import _Handler, _lock_path_for_port, main
from hub.icons import IconStore

# fixture가 넣는 틱 시각. 두 틱이 15초 간격이라 chrome.exe가 active 15초가 된다.
_TICK_AT = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)


def _usage_url(base: str, start: datetime, end: datetime) -> str:
    query = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
    return f"{base}/api/usage?{query}"


@pytest.fixture
def running_server(tmp_path):
    """임시 DB를 가리키는 실제 HTTP 서버를 띄우고, 끝나면 정리한다."""
    db_path = tmp_path / "recorder.db"
    conn = open_db(db_path)
    for offset in (0, 15):
        save_tick(
            conn,
            TickSample(
                sampled_at=_TICK_AT + timedelta(seconds=offset),
                foreground_process="chrome.exe",
                windowed_processes=frozenset({"chrome.exe"}),
                seconds_since_last_input=0.0,
            ),
        )
    exe = tmp_path / "chrome.exe"
    exe.write_bytes(b"fake exe")
    save_process_paths(conn, {"chrome.exe": str(exe)})
    conn.close()

    _Handler.db_path = db_path
    # 실제 Win32 추출 대신 가짜 추출기를 써서 플랫폼과 무관하게 응답 규약만 본다.
    _Handler.icon_store = IconStore(tmp_path / "icons", lambda path: b"PNG-fake")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_usage_endpoint_reflects_allowed_localhost_origin(running_server) -> None:
    """apps/ui가 127.0.0.1의 다른 포트에서 fetch하므로, 그 origin은 허용해서
    돌려줘야 브라우저가 응답을 읽을 수 있다."""
    request = urllib.request.Request(
        _usage_url(running_server, _TICK_AT, _TICK_AT + timedelta(hours=1)),
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
        assert response.headers["Vary"] == "Origin"
        payload = json.loads(response.read())

    assert "start" in payload
    assert "end" in payload
    assert "by_process" in payload


def test_usage_endpoint_does_not_allow_arbitrary_origins(running_server) -> None:
    """사용 기록(개인 활동 정보)이 들어 있는 응답을, 사용자가 띄워둔 아무
    웹사이트나 fetch해서 읽어가면 안 된다 — 허용되지 않은 origin에는 CORS
    헤더를 안 보내서 브라우저가 읽기를 막게 해야 한다."""
    request = urllib.request.Request(
        _usage_url(running_server, _TICK_AT, _TICK_AT + timedelta(hours=1)),
        headers={"Origin": "http://evil.example"},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert "Access-Control-Allow-Origin" not in response.headers


def test_usage_endpoint_returns_503_when_db_is_missing(tmp_path) -> None:
    """DB 파일이 아직 없으면(recorder가 한 번도 안 돈 경우), 응답 없이 연결이
    끊기는 대신 503으로 알려야 한다."""
    _Handler.db_path = tmp_path / "missing.db"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                _usage_url(
                    f"http://127.0.0.1:{server.server_port}",
                    _TICK_AT,
                    _TICK_AT + timedelta(hours=1),
                ),
                timeout=2,
            )
        assert exc_info.value.code == 503
        assert json.loads(exc_info.value.read())["error"]["code"] == "unavailable"
    finally:
        server.shutdown()


def test_usage_endpoint_accepts_offset_bounds(running_server) -> None:
    """apps/ui가 로컬 타임존 경계를 넘기므로, +09:00 같은 오프셋(퍼센트
    인코딩)을 받아도 같은 시각의 틱이 잡혀야 한다."""
    kst = timezone(timedelta(hours=9))
    start = (_TICK_AT - timedelta(minutes=1)).astimezone(kst)
    end = (_TICK_AT + timedelta(minutes=1)).astimezone(kst)

    with urllib.request.urlopen(_usage_url(running_server, start, end), timeout=2) as response:
        payload = json.loads(response.read())

    assert payload["by_process"][0]["process"] == "chrome.exe"
    assert payload["by_process"][0]["active_seconds"] == 15.0


def test_usage_endpoint_accepts_two_hour_dst_month(running_server) -> None:
    """시계가 2시간 되돌아가는 지역(Antarctica/Troll)의 10월은 31일 2시간이다."""
    start = _TICK_AT - timedelta(minutes=1)
    end = start + timedelta(days=31, hours=2)

    with urllib.request.urlopen(_usage_url(running_server, start, end), timeout=2) as response:
        assert response.status == 200


@pytest.mark.parametrize(
    "query",
    [
        "",  # start/end 둘 다 없음
        "start=2026-10-28T00:00:00Z",  # end 없음
        "start=yesterday&end=today",  # ISO 8601 아님
        "start=2026-10-28T00:00:00&end=2026-10-29T00:00:00",  # 타임존 없음
        "start=2026-10-29T00:00:00Z&end=2026-10-28T00:00:00Z",  # start >= end
        "start=2026-01-01T00:00:00Z&end=2026-03-01T00:00:00Z",  # 31일 초과
        # UTC로 바꾸면 표현 범위를 벗어나는 값(OverflowError)도 400이어야 한다.
        "start=0001-01-01T00:00:00%2B01:00&end=0001-01-02T00:00:00%2B01:00",
        # 인코딩 안 된 "+"는 공백으로 디코딩돼 ISO 8601이 깨진다.
        "start=2026-10-28T00:00:00+09:00&end=2026-10-29T00:00:00+09:00",
    ],
)
def test_usage_endpoint_rejects_invalid_bounds(running_server, query) -> None:
    """잘못된 start/end는 조용히 넘어가지 말고 400으로 알려야 한다."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/api/usage?{query}", timeout=2)

    assert exc_info.value.code == 400
    error = json.loads(exc_info.value.read())["error"]
    assert error["code"] == "invalid_request"
    assert error["message"]  # 이유가 비어 있으면 클라이언트가 보여줄 게 없다


def test_unknown_path_returns_404(running_server) -> None:
    """정의되지 않은 경로는 404로 응답해야 한다(서버가 그냥 멈추면 안 됨)."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/unknown", timeout=2)

    assert exc_info.value.code == 404
    assert json.loads(exc_info.value.read())["error"]["code"] == "not_found"


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


def test_icon_endpoint_serves_png_with_cache_headers(running_server) -> None:
    with urllib.request.urlopen(f"{running_server}/api/icons/chrome.exe", timeout=2) as response:
        body = response.read()
        headers = response.headers

    assert body == b"PNG-fake"
    assert headers["Content-Type"] == "image/png"
    assert "max-age" in headers["Cache-Control"]
    assert headers["ETag"]


def test_icon_endpoint_returns_304_for_matching_etag(running_server) -> None:
    url = f"{running_server}/api/icons/chrome.exe"
    with urllib.request.urlopen(url, timeout=2) as response:
        etag = response.headers["ETag"]

    request = urllib.request.Request(url, headers={"If-None-Match": etag})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=2)

    assert exc_info.value.code == 304


def test_icon_endpoint_treats_a_pre_migration_database_as_no_icon(tmp_path) -> None:
    """exe_path 컬럼이 아직 없는 옛 DB는 503이 아니라 아이콘 없음(404)이어야 한다."""
    import sqlite3

    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(old_db)
    conn.execute("CREATE TABLE processes (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO processes (name) VALUES ('chrome.exe')")
    conn.commit()
    conn.close()

    _Handler.db_path = old_db
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/api/icons/chrome.exe", timeout=2
            )
        assert exc_info.value.code == 404
    finally:
        server.shutdown()


@pytest.mark.parametrize("name", ["unknown.exe", "..%2F..%2Fwindows%2Fsystem32%2Fnotepad.exe"])
def test_icon_endpoint_404_for_unknown_process_and_never_opens_arbitrary_paths(
    running_server, name
) -> None:
    """이름은 DB에 기록된 프로세스만 허용한다 — 경로처럼 생긴 값으로 파일을 읽을 수 없다."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/api/icons/{name}", timeout=2)

    assert exc_info.value.code == 404
    assert json.loads(exc_info.value.read())["error"]["code"] == "not_found"
    assert "max-age" in exc_info.value.headers["Cache-Control"]  # 없음도 잠시 캐시


def _process_url(base: str, name: str, edges: list[datetime]) -> str:
    query = urllib.parse.urlencode({"edges": ",".join(e.isoformat() for e in edges)})
    return f"{base}/api/processes/{urllib.parse.quote(name)}/usage?{query}"


def test_process_usage_endpoint_returns_one_row_per_bucket(running_server) -> None:
    edges = [_TICK_AT - timedelta(minutes=1), _TICK_AT + timedelta(minutes=1), _TICK_AT + timedelta(hours=1)]

    with urllib.request.urlopen(_process_url(running_server, "chrome.exe", edges), timeout=2) as response:
        payload = json.loads(response.read())

    assert payload["process"] == "chrome.exe"
    assert len(payload["buckets"]) == 2
    assert payload["buckets"][0]["active_seconds"] == 15.0
    assert payload["buckets"][1]["total_seconds"] == 0.0


def test_process_usage_endpoint_404_for_unknown_process(running_server) -> None:
    edges = [_TICK_AT, _TICK_AT + timedelta(hours=1)]

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(_process_url(running_server, "nope.exe", edges), timeout=2)

    assert exc_info.value.code == 404
    assert json.loads(exc_info.value.read())["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "edges",
    [
        "",  # 없음
        "2026-10-28T00:00:00Z",  # 1개
        "2026-10-28T01:00:00Z,2026-10-28T00:00:00Z",  # 내림차순
        "2026-10-28T00:00:00,2026-10-28T01:00:00",  # 타임존 없음
        "yesterday,today",  # ISO 아님
        "2026-01-01T00:00:00Z,2026-03-01T00:00:00Z",  # 31일 초과
        ",".join(f"2026-10-28T{h:02d}:00:00Z" for h in range(24))
        + ",2026-10-29T00:00:00Z,2026-10-29T01:00:00Z,"
        + ",".join(f"2026-10-29T{h:02d}:00:00Z" for h in range(2, 12)),  # 칸 수 초과
    ],
)
def test_process_usage_endpoint_rejects_invalid_edges(running_server, edges) -> None:
    query = urllib.parse.urlencode({"edges": edges})

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/api/processes/chrome.exe/usage?{query}", timeout=2)

    assert exc_info.value.code == 400
    assert json.loads(exc_info.value.read())["error"]["code"] == "invalid_request"
