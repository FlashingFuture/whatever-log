import argparse
import http.client
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer

import pytest
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from hub.__main__ import DEFAULT_ALLOWED_ORIGINS, _Handler, parse_origin
from hub.goals_service import (
    BadRequest,
    check_write_origin,
    goal_fields,
    is_local_host,
    read_json_object,
)

UI_ORIGIN = "http://127.0.0.1:5173"
_TICK_AT = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
GOAL = {
    "name": "공부",
    "daily_target_minutes": 120,
    "weekdays": [0, 1, 2, 3, 4],
    "processes": ["chrome.exe"],
    "sites": [],
}


@pytest.fixture
def goals_server(tmp_path):
    """recorder.db(chrome.exe 15초 활성 — 그동안 youtube.com을 봄, Code.exe·Setup.tmp는 창만)와 빈 goals.db를 가리키는 실제 서버."""
    db_path = tmp_path / "recorder.db"
    conn = open_db(db_path)
    for offset in (0, 15):
        save_tick(
            conn,
            TickSample(
                sampled_at=_TICK_AT + timedelta(seconds=offset),
                foreground_process="chrome.exe",
                windowed_processes=frozenset({"chrome.exe", "Code.exe", "Setup.tmp"}),
                seconds_since_last_input=0.0,
                foreground_site="youtube.com",
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


def _call(base, method, path, body=None, *, origin=UI_ORIGIN, content_type="application/json", raw=None):
    """요청을 보내고 (상태, JSON 또는 None, 응답 헤더)를 돌려준다."""
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
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


# --- 목록·생성·수정·삭제 ---


def test_goals_start_empty_and_a_created_goal_is_listed(goals_server) -> None:
    assert _call(goals_server, "GET", "/api/goals")[:2] == (200, {"goals": []})

    status, created, headers = _call(goals_server, "POST", "/api/goals", GOAL)

    assert status == 201
    assert headers["Access-Control-Allow-Origin"] == UI_ORIGIN
    assert (created["name"], created["daily_target_minutes"]) == ("공부", 120)
    assert created["weekdays"] == [0, 1, 2, 3, 4] and created["processes"] == ["chrome.exe"]
    assert _call(goals_server, "GET", "/api/goals")[1] == {"goals": [created]}


def test_a_goal_can_be_created_without_processes_and_linked_later(goals_server) -> None:
    _, created, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "processes": []})
    assert created["processes"] == []

    status, updated, _ = _call(
        goals_server, "PUT", f"/api/goals/{created['id']}", {**GOAL, "processes": ["Code.exe", "chrome.exe"]}
    )

    assert status == 200 and updated["processes"] == ["chrome.exe", "Code.exe"]


def test_input_errors_come_back_per_field(goals_server) -> None:
    status, payload, _ = _call(
        goals_server,
        "POST",
        "/api/goals",
        {"name": "", "daily_target_minutes": "120", "weekdays": [], "processes": ["chrome.exe", "nope.exe"], "sites": []},
    )

    assert status == 400 and payload["error"]["code"] == "invalid_request"
    assert _error_fields(payload) == {
        "name": "length",
        "daily_target_minutes": "type",
        "weekdays": "empty",
        "processes[1]": "unknown_process",  # 기록된 적 없는 이름은 연결할 수 없다
    }
    assert _call(goals_server, "GET", "/api/goals")[1] == {"goals": []}


def test_a_process_already_linked_elsewhere_is_rejected(goals_server) -> None:
    _call(goals_server, "POST", "/api/goals", GOAL)

    status, payload, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "name": "운동"})

    assert status == 400 and _error_fields(payload) == {"processes": "already_linked"}


def test_update_and_delete(goals_server) -> None:
    _, created, _ = _call(goals_server, "POST", "/api/goals", GOAL)
    path = f"/api/goals/{created['id']}"

    status, updated, _ = _call(goals_server, "PUT", path, {**GOAL, "name": "코딩", "daily_target_minutes": 30})
    assert status == 200 and (updated["name"], updated["daily_target_minutes"]) == ("코딩", 30)

    assert _call(goals_server, "DELETE", path)[:2] == (204, None)
    assert _call(goals_server, "GET", "/api/goals")[1] == {"goals": []}


def test_unknown_goal_ids_are_404(goals_server) -> None:
    assert _call(goals_server, "PUT", "/api/goals/99", GOAL)[0] == 404
    assert _call(goals_server, "DELETE", "/api/goals/99")[0] == 404
    assert _call(goals_server, "PUT", "/api/goals/abc", GOAL)[0] == 404
    assert _call(goals_server, "POST", "/api/goals/1", GOAL)[0] == 404


def test_tracked_processes_lists_only_linkable_names_sorted(goals_server) -> None:
    status, payload, _ = _call(goals_server, "GET", "/api/processes", origin=None)

    assert status == 200
    assert payload == {"processes": ["chrome.exe", "Code.exe"]}  # Setup.tmp는 연결 대상이 아니다


# --- 수행 시간 ---


def test_progress_sums_the_active_time_of_linked_processes(goals_server) -> None:
    _call(goals_server, "POST", "/api/goals", GOAL)
    query = urllib.parse.urlencode(
        {"start": _TICK_AT.isoformat(), "end": (_TICK_AT + timedelta(hours=1)).isoformat()}
    )

    status, payload, _ = _call(goals_server, "GET", f"/api/goals/progress?{query}", origin=None)

    assert status == 200
    assert payload["goals"] == [
        {
            "id": 1,
            "name": "공부",
            "active_seconds": 15.0,
            "processes": [{"process": "chrome.exe", "active_seconds": 15.0}],
            "sites": [],
            "target_minutes": 120,  # 그 시각이 걸친 하루(월~금 중 하루)의 목표량
        }
    ]
    assert payload["summary"] == {
        "active_seconds": 15.0,
        "target_minutes": 120,
        "top": {"process": "chrome.exe", "active_seconds": 15.0, "site": None},
    }


# --- 구간의 목표량(달성률의 분모) ---


def _local_midnight(year: int, month: int, day: int) -> datetime:
    """이 PC의 시간대 자정. 화면이 구간 경계를 이렇게 만들어 보낸다 — 시험도 같은 방식이라 어느 시간대의 PC·CI에서든 같은 날짜로 읽힌다."""
    return datetime(year, month, day).astimezone()


def _target_progress(base, start: datetime, end: datetime) -> dict:
    query = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
    status, payload, _ = _call(base, "GET", f"/api/goals/progress?{query}", origin=None)
    assert status == 200
    return payload


def test_a_target_day_has_the_daily_target_and_a_rest_day_has_none(goals_server) -> None:
    _call(goals_server, "POST", "/api/goals", GOAL)  # 월~금 하루 120분

    wednesday = _target_progress(goals_server, _local_midnight(2026, 10, 28), _local_midnight(2026, 10, 29))
    saturday = _target_progress(goals_server, _local_midnight(2026, 10, 31), _local_midnight(2026, 11, 1))

    assert wednesday["goals"][0]["target_minutes"] == 120 and wednesday["summary"]["target_minutes"] == 120
    assert saturday["goals"][0]["target_minutes"] == 0 and saturday["summary"]["target_minutes"] == 0  # 쉬는 날은 달성률이 없다


def test_a_week_adds_up_every_target_day(goals_server) -> None:
    _call(goals_server, "POST", "/api/goals", GOAL)

    week = _target_progress(goals_server, _local_midnight(2026, 10, 26), _local_midnight(2026, 11, 2))  # 월~일

    assert week["goals"][0]["target_minutes"] == 5 * 120  # 월~금만 더한다(토·일은 쉬는 날)


def test_the_summary_target_is_the_sum_over_goals(goals_server) -> None:
    _call(goals_server, "POST", "/api/goals", GOAL)
    _call(goals_server, "POST", "/api/goals", {**GOAL, "name": "운동", "daily_target_minutes": 30, "weekdays": [2], "processes": ["Code.exe"]})  # 수요일만

    week = _target_progress(goals_server, _local_midnight(2026, 10, 26), _local_midnight(2026, 11, 2))

    assert [goal["target_minutes"] for goal in week["goals"]] == [600, 30]
    assert week["summary"]["target_minutes"] == 630


def test_dates_that_cannot_be_converted_to_local_time_are_400_not_a_dropped_connection(goals_server, monkeypatch) -> None:
    """Windows는 1970년 이전 같은 먼 날짜를 로컬 시간대로 바꾸다 OSError를 낸다 — 응답 없이 연결이 끊기지 않고 400이어야 한다."""
    import hub.__main__ as hub_main

    def broken(start, end):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(hub_main, "days_between", broken)
    query = urllib.parse.urlencode({"start": "1969-12-30T00:00:00+00:00", "end": "1969-12-31T00:00:00+00:00"})

    status, payload, _ = _call(goals_server, "GET", f"/api/goals/progress?{query}", origin=None)

    assert status == 400 and payload["error"]["code"] == "invalid_request"


def test_a_pre_1970_range_does_not_drop_the_connection_on_this_platform(goals_server) -> None:
    """실제 `days_between`로도: 이 플랫폼이 그 날짜를 못 바꾸면 400, 바꿀 수 있으면 200 — 어느 쪽이든 응답은 온다."""
    query = urllib.parse.urlencode({"start": "1969-12-30T00:00:00+00:00", "end": "1969-12-31T00:00:00+00:00"})

    status, _, _ = _call(goals_server, "GET", f"/api/goals/progress?{query}", origin=None)

    assert status in (200, 400)


def test_a_goal_without_any_recorded_time_still_has_its_target(goals_server) -> None:
    """수행한 시간이 없어도 목표량은 있다 — 달성률 0%로 보여야 한다."""
    _call(goals_server, "POST", "/api/goals", {**GOAL, "processes": ["Code.exe"]})
    day = _local_midnight(2026, 10, 20)  # 기록이 전혀 없는 날(화요일)

    payload = _target_progress(goals_server, day, day + timedelta(days=1))

    assert payload["goals"][0]["active_seconds"] == 0 and payload["goals"][0]["target_minutes"] == 120


# --- 브라우저의 사이트(세부 페이지) ---

SITE = {"browser": "chrome.exe", "domain": "youtube.com"}


def test_tracked_sites_lists_recorded_browser_sites(goals_server) -> None:
    assert _call(goals_server, "GET", "/api/tracked-sites", origin=None)[:2] == (200, {"sites": [SITE]})


def test_a_site_can_be_linked_and_counts_only_its_own_time(goals_server) -> None:
    status, created, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "processes": [], "sites": [SITE]})
    assert status == 201 and created["sites"] == [SITE]
    query = urllib.parse.urlencode(
        {"start": _TICK_AT.isoformat(), "end": (_TICK_AT + timedelta(hours=1)).isoformat()}
    )

    _, payload, _ = _call(goals_server, "GET", f"/api/goals/progress?{query}", origin=None)

    assert payload["goals"][0]["active_seconds"] == 15.0
    assert payload["goals"][0]["sites"] == [{**SITE, "active_seconds": 15.0}]
    assert payload["summary"]["top"] == {"process": "chrome.exe", "active_seconds": 15.0, "site": "youtube.com"}


def test_unrecorded_sites_and_overlaps_are_rejected_per_item(goals_server) -> None:
    status, payload, _ = _call(
        goals_server,
        "POST",
        "/api/goals",
        {**GOAL, "processes": [], "sites": [{"browser": "chrome.exe", "domain": "never.com"}, {"browser": "Code.exe", "domain": "a.com"}]},
    )
    assert status == 400 and _error_fields(payload) == {"sites[0]": "unknown_site", "sites[1]": "unknown_browser"}

    status, payload, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "sites": [SITE]})  # chrome.exe 전체 + 그 안의 사이트
    assert status == 400 and _error_fields(payload) == {"sites[0]": "overlaps_process"}


def test_a_site_already_linked_elsewhere_is_rejected(goals_server) -> None:
    _call(goals_server, "POST", "/api/goals", {**GOAL, "processes": [], "sites": [SITE]})

    status, payload, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "name": "운동", "processes": [], "sites": [SITE]})

    assert status == 400 and _error_fields(payload) == {"sites": "already_linked"}


def test_sites_is_required_like_every_other_field(goals_server) -> None:
    body = {key: value for key, value in GOAL.items() if key != "sites"}
    status, payload, _ = _call(goals_server, "POST", "/api/goals", body)
    assert status == 400 and _error_fields(payload) == {"sites": "type"}


def test_progress_requires_valid_bounds(goals_server) -> None:
    assert _call(goals_server, "GET", "/api/goals/progress", origin=None)[0] == 400


# --- 쓰기 요청 보호 ---


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://127.0.0.1.evil.example", "null"])
def test_writes_from_other_origins_are_refused_and_change_nothing(goals_server, origin) -> None:
    created = _call(goals_server, "POST", "/api/goals", {**GOAL, "name": "기존", "processes": []})[1]

    for method, path, body in (
        ("POST", "/api/goals", GOAL),
        ("PUT", f"/api/goals/{created['id']}", {**GOAL, "name": "바뀜"}),
        ("DELETE", f"/api/goals/{created['id']}", None),
    ):
        status, payload, _ = _call(goals_server, method, path, body, origin=origin)
        assert status == 403 and payload["error"]["code"] == "forbidden", (method, origin)

    assert _call(goals_server, "GET", "/api/goals")[1] == {"goals": [created]}


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""])
def test_writes_must_be_json(goals_server, content_type) -> None:
    status, payload, _ = _call(
        goals_server, "POST", "/api/goals", raw=json.dumps(GOAL).encode(), content_type=content_type
    )

    assert status == 415 and payload["error"]["code"] == "invalid_request"
    assert _call(goals_server, "GET", "/api/goals")[1] == {"goals": []}


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        (b"not json", 400),
        (b"[1, 2]", 400),
        (b'"text"', 400),
        (b"\xff\xfe", 400),
        (json.dumps({**GOAL, "admin": True}).encode(), 400),  # 모르는 칸
        pytest.param(b"x" * (40 * 1024), 413, id="too_large"),  # id를 주지 않으면 본문 전체가 테스트 이름이 된다
    ],
)
def test_malformed_bodies_are_rejected(goals_server, raw, status) -> None:
    assert _call(goals_server, "POST", "/api/goals", raw=raw)[0] == status


def test_requests_with_a_foreign_host_header_are_refused(goals_server) -> None:
    """DNS 리바인딩: 공격자 도메인이 127.0.0.1을 가리켜도 Host가 그 도메인이라 읽기·쓰기 모두 거부된다."""
    port = int(goals_server.rsplit(":", 1)[1])
    for method, path in (("GET", "/api/goals"), ("GET", "/api/usage"), ("DELETE", "/api/goals/1"), ("OPTIONS", "/api/goals")):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.putrequest(method, path, skip_host=True)
        connection.putheader("Host", "evil.example:8787")
        connection.putheader("Origin", UI_ORIGIN)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 403, (method, path)
        connection.close()


def test_preflight_is_answered_only_for_the_ui_origin(goals_server) -> None:
    ok = urllib.request.Request(f"{goals_server}/api/goals", method="OPTIONS", headers={"Origin": UI_ORIGIN})
    with urllib.request.urlopen(ok, timeout=3) as response:
        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == UI_ORIGIN
        for method in ("POST", "PUT", "DELETE"):
            assert method in response.headers["Access-Control-Allow-Methods"]
        assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]

    evil = urllib.request.Request(f"{goals_server}/api/goals", method="OPTIONS", headers={"Origin": "https://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(evil, timeout=3)
    assert exc_info.value.code == 403 and "Access-Control-Allow-Origin" not in exc_info.value.headers


def test_a_broken_goals_database_is_503_not_a_dropped_connection(goals_server, tmp_path) -> None:
    (tmp_path / "goals.db").write_bytes(b"this is not a sqlite database at all")

    assert _call(goals_server, "GET", "/api/goals")[0] == 503
    assert _call(goals_server, "POST", "/api/goals", GOAL)[0] == 503


# --- goals_service의 순수 함수 ---


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1:8787", True),
        ("localhost:5173", True),
        ("127.0.0.1", True),
        ("evil.example:8787", False),
        ("127.0.0.1.evil.example", False),
        ("127.0.0.1@evil.example", False),
        ("", False),
    ],
)
def test_is_local_host(host: str, expected: bool) -> None:
    assert is_local_host(host) is expected


def test_check_write_origin_requires_an_allowed_origin() -> None:
    check_write_origin(UI_ORIGIN, DEFAULT_ALLOWED_ORIGINS)
    for bad in (None, "", "https://127.0.0.1", "http://evil.example"):
        with pytest.raises(BadRequest) as exc_info:
            check_write_origin(bad, DEFAULT_ALLOWED_ORIGINS)
        assert exc_info.value.status == 403


def test_read_json_object_requires_a_length_and_a_json_content_type() -> None:
    body = json.dumps({"a": 1}).encode()

    assert read_json_object({"Content-Type": "application/json", "Content-Length": str(len(body))}, io.BytesIO(body)) == {"a": 1}
    assert read_json_object(
        {"Content-Type": "application/json; charset=utf-8", "Content-Length": str(len(body))}, io.BytesIO(body)
    ) == {"a": 1}
    with pytest.raises(BadRequest) as no_length:
        read_json_object({"Content-Type": "application/json"}, io.BytesIO(body))
    assert no_length.value.status == 411
    with pytest.raises(BadRequest) as zero:
        read_json_object({"Content-Type": "application/json", "Content-Length": "0"}, io.BytesIO(b""))
    assert zero.value.status == 413


def test_goal_fields_rejects_unknown_keys_and_fills_missing_ones_with_none() -> None:
    assert goal_fields({"name": "a"}) == {
        "name": "a",
        "daily_target_minutes": None,
        "weekdays": None,
        "processes": None,
        "sites": None,
    }
    with pytest.raises(BadRequest):
        goal_fields({"name": "a", "extra": 1})


# --- 리뷰 반영: 본문 검사 보강 ---


def test_a_delete_with_a_body_is_rejected_and_deletes_nothing(goals_server) -> None:
    _, created, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "processes": []})
    path = f"/api/goals/{created['id']}"

    status, payload, _ = _call(goals_server, "DELETE", path, {"x": 1})

    assert status == 400 and payload["error"]["code"] == "invalid_request"
    assert _call(goals_server, "GET", "/api/goals")[1] == {"goals": [created]}
    assert _call(goals_server, "DELETE", path)[0] == 204


def test_deeply_nested_json_is_a_400_not_a_crash(goals_server) -> None:
    deep = b"[" * 15_000 + b"]" * 15_000  # 32KB 상한 안쪽이지만 재귀 한도는 훌쩍 넘는다

    status, payload, _ = _call(goals_server, "POST", "/api/goals", raw=deep)

    assert status == 400 and payload["error"]["code"] == "invalid_request"


def test_a_truncated_body_is_rejected() -> None:
    headers = {"Content-Type": "application/json", "Content-Length": "20"}
    with pytest.raises(BadRequest) as caught:
        read_json_object(headers, io.BytesIO(b'{"name":'))
    assert caught.value.status == 400


def test_a_goal_without_links_is_saved_even_if_the_recorder_db_is_unreadable(goals_server, tmp_path) -> None:
    _Handler.db_path = tmp_path / "missing" / "recorder.db"  # 열 수 없는 기록 DB
    body = {**GOAL, "processes": [], "sites": []}

    assert _call(goals_server, "POST", "/api/goals", body)[0] == 201
    assert _call(goals_server, "POST", "/api/goals", {**GOAL, "name": "다른"})[0] == 503  # 연결이 있으면 확인이 필요하다


# --- 허용 origin은 정확히 일치해야 한다(아무 localhost 포트가 아니라) ---


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:9999", "http://localhost:3000", "http://127.0.0.1", "http://localhost:5173/"]
)
def test_another_local_web_server_cannot_read_or_write_goals(goals_server, origin) -> None:
    created = _call(goals_server, "POST", "/api/goals", {**GOAL, "processes": []})[1]

    for method, path, body in (
        ("POST", "/api/goals", GOAL),
        ("PUT", f"/api/goals/{created['id']}", {**GOAL, "name": "바뀜"}),
        ("DELETE", f"/api/goals/{created['id']}", None),
    ):
        status, payload, _ = _call(goals_server, method, path, body, origin=origin)
        assert status == 403 and payload["error"]["code"] == "forbidden", (method, origin)

    status, _, headers = _call(goals_server, "GET", "/api/goals", origin=origin)  # 읽기도 CORS 헤더가 없어 브라우저가 막는다
    assert status == 200 and "Access-Control-Allow-Origin" not in headers
    options = urllib.request.Request(f"{goals_server}/api/goals", method="OPTIONS", headers={"Origin": origin})
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(options, timeout=3)
    assert caught.value.code == 403


def test_the_origin_given_by_the_launcher_is_the_one_that_is_allowed(goals_server, monkeypatch) -> None:
    desktop_ui = "http://127.0.0.1:53412"  # desktop이 서빙하는 UI의 임의 포트
    monkeypatch.setattr(_Handler, "allowed_origins", frozenset({desktop_ui}))

    assert _call(goals_server, "POST", "/api/goals", {**GOAL, "processes": []}, origin=desktop_ui)[0] == 201
    status, payload, _ = _call(goals_server, "POST", "/api/goals", {**GOAL, "name": "다른", "processes": []}, origin=UI_ORIGIN)
    assert status == 403 and payload["error"]["code"] == "forbidden"  # 기본값이던 5173은 더 이상 허용되지 않는다


@pytest.mark.parametrize("text", ["http://localhost:5173", "http://127.0.0.1:53412"])
def test_parse_origin_accepts_local_origins(text) -> None:
    assert parse_origin(text) == text


@pytest.mark.parametrize(
    "text", ["", "*", "https://localhost:5173", "http://evil.example:5173", "http://localhost", "http://localhost:5173/", "http://localhost:99999x"]
)
def test_parse_origin_rejects_everything_else(text) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_origin(text)
