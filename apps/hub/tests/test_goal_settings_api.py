"""알림 규칙·보고서 일정 API(/api/goals/<id>/alerts, /api/goals/<id>/report-schedule)."""

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer

import pytest
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from hub.__main__ import _Handler

UI_ORIGIN = "http://127.0.0.1:5173"
_TICK_AT = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
GOAL = {"name": "공부", "daily_target_minutes": 120, "weekdays": [0, 1, 2, 3, 4], "processes": ["chrome.exe"], "sites": []}


@pytest.fixture
def goals_server(tmp_path):
    """chrome.exe가 기록된 recorder.db와 빈 goals.db를 가리키는 실제 서버(연결할 프로세스는 기록된 이름이어야 한다)."""
    db_path = tmp_path / "recorder.db"
    conn = open_db(db_path)
    for offset in (0, 15):
        save_tick(
            conn,
            TickSample(
                sampled_at=_TICK_AT + timedelta(seconds=offset),
                foreground_process="chrome.exe",
                windowed_processes=frozenset({"chrome.exe", "Code.exe"}),
                seconds_since_last_input=0.0,
            ),
        )
    conn.close()
    _Handler.db_path = db_path
    _Handler.goals_db_path = tmp_path / "goals.db"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def _call(base, method, path, body=None, *, origin=UI_ORIGIN, content_type="application/json"):
    """요청을 보내고 (상태, JSON 또는 None, 응답 헤더)를 돌려준다."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {}
    if origin:
        headers["Origin"] = origin
    if data is not None and content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(f"{base}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else None), response.headers
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, (json.loads(payload) if payload else None), error.headers


def _error_fields(payload) -> dict[str, str]:
    return {item["field"]: item["code"] for item in payload["error"]["fields"]}


ALERT = {"target_process": None, "deadline": "23:00", "min_minutes": 1, "weekdays": [0, 1, 2, 3, 4, 5, 6], "enabled": True}
SCHEDULE = {"enabled": True, "frequency": "weekly", "weekday": 0, "day_of_month": None, "send_time": "09:00"}


@pytest.fixture
def goal_id(goals_server) -> int:
    _, created, _ = _call(goals_server, "POST", "/api/goals", GOAL)
    return created["id"]


# --- 알림 규칙 ---


def test_alerts_start_empty_and_a_created_alert_is_listed(goals_server, goal_id) -> None:
    path = f"/api/goals/{goal_id}/alerts"
    assert _call(goals_server, "GET", path)[:2] == (200, {"alerts": []})

    status, created, headers = _call(goals_server, "POST", path, {**ALERT, "target_process": "chrome.exe"})

    assert status == 201 and headers["Access-Control-Allow-Origin"] == UI_ORIGIN
    assert (created["goal_id"], created["target_process"], created["deadline"]) == (goal_id, "chrome.exe", "23:00")
    assert created["weekdays"] == [0, 1, 2, 3, 4, 5, 6] and created["enabled"] is True
    assert _call(goals_server, "GET", path)[1] == {"alerts": [created]}


def test_an_alert_is_replaced_and_deleted(goals_server, goal_id) -> None:
    path = f"/api/goals/{goal_id}/alerts"
    _, created, _ = _call(goals_server, "POST", path, ALERT)
    item = f"{path}/{created['id']}"

    status, updated, _ = _call(goals_server, "PUT", item, {**ALERT, "deadline": "22:30", "enabled": False})
    assert status == 200 and (updated["deadline"], updated["enabled"]) == ("22:30", False)

    assert _call(goals_server, "DELETE", item)[0] == 204
    assert _call(goals_server, "DELETE", item)[0] == 404
    assert _call(goals_server, "GET", path)[1] == {"alerts": []}


def test_alert_input_errors_come_back_per_field(goals_server, goal_id) -> None:
    status, payload, _ = _call(
        goals_server,
        "POST",
        f"/api/goals/{goal_id}/alerts",
        {**ALERT, "target_process": "Code.exe", "deadline": "25:00", "min_minutes": 0},
    )

    assert status == 400
    assert _error_fields(payload) == {"target_process": "not_linked", "deadline": "format", "min_minutes": "range"}


def test_unknown_alert_fields_are_rejected(goals_server, goal_id) -> None:
    status, payload, _ = _call(goals_server, "POST", f"/api/goals/{goal_id}/alerts", {**ALERT, "extra": 1})
    assert status == 400 and "extra" in payload["error"]["message"]


def test_alerts_of_a_missing_goal_are_not_found(goals_server) -> None:
    assert _call(goals_server, "GET", "/api/goals/99/alerts")[0] == 404
    assert _call(goals_server, "POST", "/api/goals/99/alerts", ALERT)[0] == 404


def test_an_alert_cannot_be_reached_through_another_goal(goals_server, goal_id) -> None:
    _, other, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "name": "운동", "processes": []})
    _, created, _ = _call(goals_server, "POST", f"/api/goals/{goal_id}/alerts", ALERT)
    wrong = f"/api/goals/{other['id']}/alerts/{created['id']}"

    assert _call(goals_server, "PUT", wrong, ALERT)[0] == 404
    assert _call(goals_server, "DELETE", wrong)[0] == 404
    assert len(_call(goals_server, "GET", f"/api/goals/{goal_id}/alerts")[1]["alerts"]) == 1


def test_deleting_the_goal_deletes_its_alerts(goals_server, goal_id) -> None:
    _call(goals_server, "POST", f"/api/goals/{goal_id}/alerts", ALERT)
    _call(goals_server, "DELETE", f"/api/goals/{goal_id}")
    assert _call(goals_server, "GET", f"/api/goals/{goal_id}/alerts")[0] == 404


# --- 보고서 일정 ---


def test_a_schedule_starts_empty_then_is_saved_replaced_and_deleted(goals_server, goal_id) -> None:
    path = f"/api/goals/{goal_id}/report-schedule"
    assert _call(goals_server, "GET", path)[:2] == (200, {"schedule": None})

    status, saved, _ = _call(goals_server, "PUT", path, SCHEDULE)
    assert status == 200 and (saved["frequency"], saved["weekday"], saved["send_time"]) == ("weekly", 0, "09:00")
    assert _call(goals_server, "GET", path)[1] == {"schedule": saved}

    status, replaced, _ = _call(
        goals_server, "PUT", path, {**SCHEDULE, "frequency": "monthly", "weekday": None, "day_of_month": 10}
    )
    assert status == 200 and (replaced["weekday"], replaced["day_of_month"]) == (None, 10)

    assert _call(goals_server, "DELETE", path)[0] == 204
    assert _call(goals_server, "DELETE", path)[0] == 404
    assert _call(goals_server, "GET", path)[1] == {"schedule": None}


def test_schedule_input_errors_come_back_per_field(goals_server, goal_id) -> None:
    status, payload, _ = _call(
        goals_server,
        "PUT",
        f"/api/goals/{goal_id}/report-schedule",
        {**SCHEDULE, "frequency": "monthly", "weekday": 0, "day_of_month": 31},
    )
    assert status == 400
    assert _error_fields(payload) == {"day_of_month": "range", "weekday": "unexpected"}


def test_a_schedule_of_a_missing_goal_is_not_found(goals_server) -> None:
    assert _call(goals_server, "GET", "/api/goals/99/report-schedule")[0] == 404
    assert _call(goals_server, "PUT", "/api/goals/99/report-schedule", SCHEDULE)[0] == 404


# --- 쓰기 보호는 목표 API와 같다 ---


@pytest.mark.parametrize("origin", [None, "http://evil.example"])
def test_writes_need_an_allowed_origin(goals_server, goal_id, origin) -> None:
    for method, path, body in (
        ("POST", f"/api/goals/{goal_id}/alerts", ALERT),
        ("PUT", f"/api/goals/{goal_id}/report-schedule", SCHEDULE),
        ("DELETE", f"/api/goals/{goal_id}/report-schedule", None),
    ):
        assert _call(goals_server, method, path, body, origin=origin)[0] == 403


def test_writes_need_a_json_body_and_deletes_must_not_have_one(goals_server, goal_id) -> None:
    path = f"/api/goals/{goal_id}/alerts"
    assert _call(goals_server, "POST", path, ALERT, content_type="text/plain")[0] == 415
    _, created, _ = _call(goals_server, "POST", path, ALERT)
    assert _call(goals_server, "DELETE", f"{path}/{created['id']}", {"x": 1})[0] == 400
