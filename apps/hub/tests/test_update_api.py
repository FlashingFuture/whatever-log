"""새 버전 확인 API(docs/updates.md 1단계): 상태 읽기, 지금 확인, 켜고 끄기. GitHub는 가짜 목록으로 바꾼다."""

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest
from common.updates import RELEASES_PAGE, UpdateChecker

from hub.__main__ import _Handler
from hub.external_links import LINKS

UI_ORIGIN = "http://127.0.0.1:5173"


@pytest.fixture
def server(tmp_path):
    calls: list[int] = []
    releases = [{"tag_name": "v1.0.0", "prerelease": False, "draft": False, "html_url": f"{RELEASES_PAGE}/tag/v1.0.0"}]

    def fetch():
        calls.append(1)
        return releases

    saved = (_Handler.update_checker, _Handler.allowed_origins)
    _Handler.update_checker = UpdateChecker(tmp_path / "update-check.json", "1.0.0-beta.2", supported=True, fetch=fetch)
    _Handler.allowed_origins = frozenset({UI_ORIGIN})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield httpd.server_port, calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        _Handler.update_checker, _Handler.allowed_origins = saved


def call(port, method, path, body=None, *, origin=UI_ORIGIN):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Origin": origin} if origin else {}
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    return response.status, (json.loads(raw) if raw else None)


def test_the_state_tells_whether_a_newer_version_exists(server) -> None:
    port, calls = server

    status, body = call(port, "GET", "/api/update")

    assert status == 200
    assert body["available"] is True and body["current"] == "1.0.0-beta.2"
    assert body["latest"]["version"] == "1.0.0" and body["latest"]["url"].startswith(RELEASES_PAGE)
    call(port, "GET", "/api/update")
    assert len(calls) == 1  # 하루에 한 번만 묻는다


def test_check_now_asks_again(server) -> None:
    port, calls = server
    call(port, "GET", "/api/update")
    assert call(port, "POST", "/api/update/check")[0] == 200
    assert len(calls) == 2


def test_turning_it_off_stops_asking_and_needs_the_apps_origin(server) -> None:
    port, calls = server
    assert call(port, "POST", "/api/update/settings", {"enabled": False}, origin="http://evil.example")[0] == 403
    status, body = call(port, "POST", "/api/update/settings", {"enabled": False})
    assert status == 200 and body["enabled"] is False
    assert call(port, "POST", "/api/update/check")[1]["available"] is False
    assert calls == []
    assert call(port, "POST", "/api/update/settings", {"enabled": "no"})[0] == 400
    assert call(port, "POST", "/api/update/check", origin=None)[0] == 403


def test_the_release_page_is_one_of_the_fixed_links() -> None:
    assert LINKS["releases"] == RELEASES_PAGE


def test_later_is_kept_by_the_hub(server) -> None:
    port, _ = server
    call(port, "GET", "/api/update")
    status, body = call(port, "POST", "/api/update/settings", {"dismissed": "1.0.0"})
    assert status == 200 and body["dismissed"] == "1.0.0"
    assert call(port, "GET", "/api/update")[1]["dismissed"] == "1.0.0"
    assert call(port, "POST", "/api/update/settings", {"dismissed": "soon"})[0] == 400
    assert call(port, "POST", "/api/update/settings", {"dismissed": "1.0.0", "enabled": False})[0] == 400
