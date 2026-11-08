import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cloud.api import (
    GoalConflict,
    NotAuthorized,
    ProgressEntry,
    RemoteGoal,
    ServerApi,
    ServerError,
    ServerUnreachable,
)

TOKEN = "t" * 43
LIVE = {
    "id": "00000000-0000-4000-8000-000000000001",
    "deleted": False,
    "name": "공부",
    "daily_target_minutes": 120,
    "weekdays": [0, 1],
    "revision": 2,
    "updated_at": "2026-11-06T03:00:00.000Z",
}
GONE = {"id": "00000000-0000-4000-8000-000000000002", "deleted": True, "revision": 3, "updated_at": "t"}


class _Server:
    """정해 둔 응답을 돌려주는 실제 HTTP 서버. 받은 요청(메서드, 주소, 헤더, 본문)을 기록한다."""

    def __init__(self, status: int, body: object) -> None:
        self.requests: list[dict] = []
        outer = self
        raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(length)
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "auth": self.headers["Authorization"],
                        "agent": self.headers["User-Agent"],
                        "type": self.headers["Content-Type"],
                        "body": json.loads(data) if data else None,
                    }
                )
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_PUT = do_DELETE = do_POST = _handle

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve():
    servers: list[_Server] = []

    def make(status: int, body: object = b"") -> _Server:
        servers.append(_Server(status, body))
        return servers[-1]

    yield make
    for server in servers:
        server.close()


def test_every_request_carries_the_bearer_token_and_a_non_default_user_agent(serve) -> None:
    server = serve(200, {"goals": []})

    ServerApi(server.url, TOKEN).list_goals()

    (request,) = server.requests
    assert request["auth"] == f"Bearer {TOKEN}"
    assert not request["agent"].startswith("Python-urllib")  # Cloudflare가 봇으로 막는다


def test_list_goals_parses_live_and_deleted_goals(serve) -> None:
    server = serve(200, {"goals": [LIVE, GONE]})

    live, gone = ServerApi(server.url, TOKEN).list_goals()

    assert live == RemoteGoal(LIVE["id"], False, 2, LIVE["updated_at"], "공부", 120, frozenset({0, 1}))
    assert gone == RemoteGoal(GONE["id"], True, 3, "t")
    assert server.requests[0]["path"] == "/goals"


@pytest.mark.parametrize(
    "body",
    [
        {"goals": [{**LIVE, "revision": "2"}]},
        {"goals": [{**LIVE, "weekdays": "0,1"}]},
        {"goals": [{k: v for k, v in LIVE.items() if k != "name"}]},
        {"goals": "x"},
        {"nope": []},
        b"not json",
    ],
)
def test_a_response_with_the_wrong_shape_is_rejected_not_trusted(serve, body) -> None:
    server = serve(200, body)

    with pytest.raises(ServerError) as raised:
        ServerApi(server.url, TOKEN).list_goals()

    assert raised.value.code == "bad_response"


def test_put_goal_sends_the_wire_format(serve) -> None:
    server = serve(201, LIVE)

    goal = ServerApi(server.url, TOKEN).put_goal(
        LIVE["id"], name="공부", daily_target_minutes=120, weekdays={1, 0}, base_revision=0
    )

    (request,) = server.requests
    assert request["method"] == "PUT" and request["path"] == f"/goals/{LIVE['id']}"
    assert request["type"] == "application/json"
    assert request["body"] == {"name": "공부", "daily_target_minutes": 120, "weekdays": [0, 1], "base_revision": 0}
    assert goal.revision == 2


def test_a_409_becomes_a_goal_conflict_with_the_servers_current_value(serve) -> None:
    server = serve(409, {"error": {"code": "conflict", "message": "다른 기기에서 먼저 바뀌었습니다."}, "current": LIVE})

    with pytest.raises(GoalConflict) as raised:
        ServerApi(server.url, TOKEN).put_goal(LIVE["id"], name="x", daily_target_minutes=1, weekdays=[0], base_revision=1)

    assert raised.value.code == "conflict" and raised.value.current.revision == 2


def test_a_409_without_a_usable_current_value_still_raises_a_conflict(serve) -> None:
    server = serve(409, {"error": {"code": "duplicate_name", "message": "같은 이름"}})

    with pytest.raises(GoalConflict) as raised:
        ServerApi(server.url, TOKEN).put_goal(LIVE["id"], name="x", daily_target_minutes=1, weekdays=[0], base_revision=0)

    assert raised.value.code == "duplicate_name" and raised.value.current is None


def test_401_is_not_authorized_and_carries_no_token(serve) -> None:
    server = serve(401, {"error": {"code": "invalid_token", "message": "x"}})

    with pytest.raises(NotAuthorized) as raised:
        ServerApi(server.url, TOKEN).list_goals()

    assert TOKEN not in str(raised.value)


def test_other_http_errors_become_server_errors_with_the_servers_message(serve) -> None:
    server = serve(400, {"error": {"code": "invalid_request", "message": "name은 1~50자여야 합니다."}})

    with pytest.raises(ServerError) as raised:
        ServerApi(server.url, TOKEN).put_goal("g", name="", daily_target_minutes=1, weekdays=[0], base_revision=0)

    assert (raised.value.status, raised.value.code) == (400, "invalid_request")
    assert "1~50자" in raised.value.message


def test_an_error_page_that_is_not_json_still_raises_a_server_error(serve) -> None:
    server = serve(502, b"<html>bad gateway</html>")

    with pytest.raises(ServerError) as raised:
        ServerApi(server.url, TOKEN).list_goals()

    assert raised.value.status == 502


def test_an_unreachable_server_is_reported_separately(serve) -> None:
    with pytest.raises(ServerUnreachable):
        ServerApi("http://127.0.0.1:9", TOKEN).list_goals()


def test_a_connection_cut_mid_error_body_is_a_server_error_not_a_crash() -> None:
    import http.client

    class Cut(urllib.error.HTTPError):
        def read(self, *args):
            raise http.client.IncompleteRead(b"")

    def opener(request, timeout):
        raise Cut("https://s", 502, "bad", {}, None)

    with pytest.raises(ServerError) as raised:
        ServerApi("https://s", TOKEN, opener=opener).list_goals()

    assert raised.value.status == 502


def test_delete_goal_treats_404_as_already_gone(serve) -> None:
    assert ServerApi(serve(204).url, TOKEN).delete_goal("g") is True
    assert ServerApi(serve(404, {"error": {"code": "not_found", "message": "x"}}).url, TOKEN).delete_goal("g") is False
    with pytest.raises(ServerError):
        ServerApi(serve(500, {"error": {"code": "internal_error", "message": "x"}}).url, TOKEN).delete_goal("g")


def test_put_progress_sends_entries_and_reads_the_result(serve) -> None:
    server = serve(200, {"accepted": 1, "ignored_goal_ids": ["gone"]})

    result = ServerApi(server.url, TOKEN).put_progress(
        "device-1", [ProgressEntry("g1", "2026-11-05", 95, 120), ProgressEntry("gone", "2026-11-05", 5, 120)]
    )

    assert (result.accepted, result.ignored_goal_ids) == (1, ("gone",))
    assert server.requests[0]["body"] == {
        "device_id": "device-1",
        "entries": [
            {"goal_id": "g1", "day": "2026-11-05", "minutes": 95, "target_minutes": 120},
            {"goal_id": "gone", "day": "2026-11-05", "minutes": 5, "target_minutes": 120},
        ],
    }


def test_get_progress_parses_days_and_sends_the_range(serve) -> None:
    server = serve(
        200,
        {"days": [{"goal_id": "g1", "day": "2026-11-05", "minutes": 95, "target_minutes": 120, "percent": 79, "devices": 2}]},
    )

    (day,) = ServerApi(server.url, TOKEN).get_progress("2026-11-01", "2026-11-06")

    assert (day.minutes, day.percent, day.devices) == (95, 79, 2)
    assert server.requests[0]["path"] == "/progress?from=2026-11-01&to=2026-11-06"


def test_list_devices_parses_ids_times_and_row_counts_and_nothing_else(serve) -> None:
    from cloud import DeviceInfo

    server = serve(
        200,
        {"devices": [{"device_id": "d-1", "last_sent_at": "2026-11-06T03:01:00.000Z", "rows": 4}]},
    )

    assert ServerApi(server.url, TOKEN).list_devices() == [DeviceInfo("d-1", "2026-11-06T03:01:00.000Z", 4)]
    assert server.requests[0]["method"] == "GET" and server.requests[0]["path"] == "/devices"


@pytest.mark.parametrize(
    "body",
    [{"devices": [{"device_id": "d", "last_sent_at": "t", "rows": "4"}]}, {"devices": [{"device_id": "d"}]}, {"devices": 5}, {}],
)
def test_a_device_list_with_the_wrong_shape_is_rejected(serve, body) -> None:
    with pytest.raises(ServerError) as raised:
        ServerApi(serve(200, body).url, TOKEN).list_devices()

    assert raised.value.code == "bad_response"


def test_delete_device_and_delete_account_use_the_right_verbs_and_paths(serve) -> None:
    server = serve(204)
    api = ServerApi(server.url, TOKEN)

    api.delete_device("d-1")
    api.delete_account()

    assert [(r["method"], r["path"]) for r in server.requests] == [("DELETE", "/devices/d-1"), ("DELETE", "/account")]
    assert all(r["auth"] == f"Bearer {TOKEN}" for r in server.requests)


def test_delete_account_failures_are_raised_not_swallowed(serve) -> None:
    with pytest.raises(NotAuthorized):
        ServerApi(serve(401, {"error": {"code": "invalid_token", "message": "x"}}).url, TOKEN).delete_account()
    with pytest.raises(ServerError):
        ServerApi(serve(500, {"error": {"code": "internal_error", "message": "x"}}).url, TOKEN).delete_account()
    with pytest.raises(ServerUnreachable):
        ServerApi("http://127.0.0.1:9", TOKEN).delete_account()
