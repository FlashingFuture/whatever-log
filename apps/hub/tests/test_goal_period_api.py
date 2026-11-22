"""목표의 기간(start_date·end_date) API와, 기간이 있는 목표의 수행 시간이 기간 안의 날만 세는지(`/api/goals/progress`)."""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from http.server import ThreadingHTTPServer

import pytest
from goals import GoalStore
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from hub.__main__ import _Handler

UI_ORIGIN = "http://127.0.0.1:5173"
_TICK_AT = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
TICK_DAY = _TICK_AT.astimezone().date()  # 이 PC의 시간대로 본 기록한 날(시험이 어느 시간대에서 돌아도 같은 날을 가리키게)
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


@pytest.fixture
def server(tmp_path):
    """chrome.exe가 TICK_DAY에 기록된 recorder.db와 빈 goals.db를 가리키는 실제 서버."""
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
    conn.close()
    _Handler.db_path = db_path
    _Handler.goals_db_path = tmp_path / "goals.db"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()


def _call(base, method, path, body=None, *, origin=UI_ORIGIN):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {}
    if origin:
        headers["Origin"] = origin
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, (json.loads(payload) if payload else None)


def _fields(payload) -> dict[str, str]:
    return {item["field"]: item["code"] for item in payload["error"]["fields"]}


def _today() -> date:
    return datetime.now().astimezone().date()


def _goal(**period):
    return {"name": "공부", "daily_target_minutes": 60, "weekdays": ALL_DAYS, "processes": ["chrome.exe"], "sites": [], **period}


# --- 기간 입력 ---


def test_a_goal_is_created_with_a_period_and_listed_with_it(server) -> None:
    start, end = _today() + timedelta(days=3), _today() + timedelta(days=10)
    status, created = _call(server, "POST", "/api/goals", _goal(start_date=start.isoformat(), end_date=end.isoformat()))
    assert status == 201
    assert (created["start_date"], created["end_date"]) == (start.isoformat(), end.isoformat())
    assert _call(server, "GET", "/api/goals")[1] == {"goals": [created]}


def test_a_goal_without_a_period_has_null_dates(server) -> None:
    _, created = _call(server, "POST", "/api/goals", _goal())
    assert (created["start_date"], created["end_date"]) == (None, None)


def test_period_input_errors_come_back_per_field(server) -> None:
    today = _today()
    cases = [
        ({"start_date": (today + timedelta(days=2)).isoformat()}, {"end_date": "incomplete"}),
        (
            {"start_date": (today + timedelta(days=5)).isoformat(), "end_date": (today + timedelta(days=4)).isoformat()},
            {"end_date": "order"},
        ),
        ({"start_date": (today - timedelta(days=1)).isoformat(), "end_date": (today + timedelta(days=4)).isoformat()}, {"start_date": "past"}),
        ({"start_date": "내일", "end_date": "모레"}, {"start_date": "format", "end_date": "format"}),
        ({"start_date": 20261110, "end_date": "2026-12-01"}, {"start_date": "type"}),
    ]
    for period, expected in cases:
        status, payload = _call(server, "POST", "/api/goals", _goal(**period))
        assert status == 400 and _fields(payload) == expected, period
    assert _call(server, "GET", "/api/goals")[1] == {"goals": []}


def test_a_started_goal_can_be_edited_without_touching_its_period(server) -> None:
    today = _today()
    with GoalStore(_Handler.goals_db_path) as store:  # 이미 시작한 목표(시작일이 어제)를 만들어 둔다
        goal = store.create(
            name="공부", daily_target_minutes=60, weekdays=ALL_DAYS, processes=[],
            start_date=(today - timedelta(days=1)).isoformat(), end_date=(today + timedelta(days=9)).isoformat(),
            today=today - timedelta(days=2),
        )
    body = {**_goal(start_date=goal.start_date.isoformat(), end_date=goal.end_date.isoformat()), "processes": [], "daily_target_minutes": 90}
    status, updated = _call(server, "PUT", f"/api/goals/{goal.id}", body)
    assert status == 200 and updated["daily_target_minutes"] == 90 and updated["start_date"] == goal.start_date.isoformat()
    # 시작일을 다른 과거 날짜로 바꾸는 것은 거부한다
    bad = {**body, "start_date": (today - timedelta(days=5)).isoformat()}
    status, payload = _call(server, "PUT", f"/api/goals/{goal.id}", bad)
    assert status == 400 and _fields(payload) == {"start_date": "past"}


# --- 수행 시간은 기간 안의 날만 센다 ---


def _progress(server, start: date, end: date):
    local = datetime.now().astimezone().tzinfo
    query = urllib.parse.urlencode(
        {
            "start": datetime.combine(start, datetime.min.time(), tzinfo=local).astimezone(UTC).isoformat(),
            "end": datetime.combine(end, datetime.min.time(), tzinfo=local).astimezone(UTC).isoformat(),
        }
    )
    status, payload = _call(server, "GET", f"/api/goals/progress?{query}", origin=None)
    assert status == 200
    return {goal["name"]: goal for goal in payload["goals"]}


def test_time_outside_the_period_is_not_counted(server) -> None:
    with GoalStore(_Handler.goals_db_path) as store:
        inside = store.create(
            name="기간 안", daily_target_minutes=60, weekdays=ALL_DAYS, processes=["chrome.exe"], known_processes=["chrome.exe"],
            start_date=(TICK_DAY - timedelta(days=1)).isoformat(), end_date=(TICK_DAY + timedelta(days=1)).isoformat(),
            today=TICK_DAY - timedelta(days=2),
        )
        outside = store.create(
            name="기간 밖", daily_target_minutes=60, weekdays=ALL_DAYS, processes=["Code.exe"], known_processes=["Code.exe"],
            start_date=(TICK_DAY + timedelta(days=5)).isoformat(), end_date=(TICK_DAY + timedelta(days=9)).isoformat(),
            today=TICK_DAY - timedelta(days=2),
        )
    by_name = _progress(server, TICK_DAY - timedelta(days=3), TICK_DAY + timedelta(days=12))
    assert by_name["기간 안"]["active_seconds"] == 15.0
    assert by_name["기간 밖"]["active_seconds"] == 0.0
    assert (by_name["기간 안"]["start_date"], by_name["기간 안"]["end_date"]) == ((TICK_DAY - timedelta(days=1)).isoformat(), (TICK_DAY + timedelta(days=1)).isoformat())
    assert inside.id != outside.id


def test_the_same_recorded_time_is_dropped_when_the_goal_period_excludes_that_day(server) -> None:
    with GoalStore(_Handler.goals_db_path) as store:
        store.create(
            name="지난 기간", daily_target_minutes=60, weekdays=ALL_DAYS, processes=["chrome.exe"], known_processes=["chrome.exe"],
            start_date=(TICK_DAY + timedelta(days=2)).isoformat(), end_date=(TICK_DAY + timedelta(days=6)).isoformat(),
            today=TICK_DAY - timedelta(days=1),
        )
        store.create(
            name="기간 없음", daily_target_minutes=60, weekdays=ALL_DAYS, processes=["Code.exe"], known_processes=["Code.exe"]
        )
    by_name = _progress(server, TICK_DAY - timedelta(days=1), TICK_DAY + timedelta(days=8))
    assert by_name["지난 기간"]["active_seconds"] == 0.0  # 기록은 기간보다 앞선 날의 것이다
    assert by_name["지난 기간"]["target_minutes"] == 5 * 60  # 목표량은 기간 안의 5일만 센다
    assert by_name["기간 없음"]["target_minutes"] == 9 * 60  # 구간 9일 전부


def test_a_goal_without_a_period_still_counts_the_whole_range(server) -> None:
    with GoalStore(_Handler.goals_db_path) as store:
        store.create(name="무기한", daily_target_minutes=60, weekdays=ALL_DAYS, processes=["chrome.exe"], known_processes=["chrome.exe"])
    assert _progress(server, TICK_DAY - timedelta(days=1), TICK_DAY + timedelta(days=1))["무기한"]["active_seconds"] == 15.0
