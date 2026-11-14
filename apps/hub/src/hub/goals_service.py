"""목표 API(/api/goals, /api/processes, /api/tracked-sites)의 HTTP와 무관한 부분 — 요청 검사, 본문 해석, 응답 만들기.

핸들러(`hub.__main__._Handler`)는 얇게 두고, 규칙은 여기 순수 함수로 둔다(소켓 없이 테스트한다). 목표가
무엇이고 무엇이 올바른 입력인지는 packages/goals가 정하고, 여기는 그것을 HTTP 요청·응답 모양으로
옮길 뿐이다.

쓰기 요청(POST/PUT/DELETE)이 생기면서 hub는 처음으로 "상태를 바꾸는" API를 갖는다. 방문 중인 아무
웹페이지가 127.0.0.1로 요청을 보내 목표를 지우거나 바꾸지 못하게 아래를 모두 적용한다:
- Host 헤더가 로컬 주소여야 한다(DNS 리바인딩으로 다른 이름이 이 주소를 가리켜도 거부). 읽기에도 적용한다.
- Origin이 허용된 UI여야 한다(없어도 거부 — 브라우저는 교차 출처 쓰기에 항상 Origin을 보낸다).
- 본문은 `Content-Type: application/json`이어야 한다(폼 전송 같은 "단순 요청"이 통과하지 못하게).
"""

import json
import re
from collections.abc import Collection, Mapping
from typing import Any, BinaryIO

from aggregation.range import RangeUsage
from goals import (
    Goal,
    GoalAlert,
    GoalProgress,
    GoalValidationError,
    ProgressSummary,
    ReportSchedule,
    TopTarget,
    compute_progress,
)

from common import api_error

# 목표 입력의 모든 칸은 이 다섯 개뿐이다 — 모르는 칸이 있으면 오타나 다른 API의 본문일 수 있어 거부한다.
GOAL_FIELDS = ("name", "daily_target_minutes", "weekdays", "processes", "sites")
# 알림 규칙·보고서 일정 입력의 칸(docs/goal-management.md). 모르는 칸은 거부한다.
ALERT_FIELDS = ("target_process", "deadline", "min_minutes", "weekdays", "enabled")
SCHEDULE_FIELDS = ("enabled", "frequency", "weekday", "day_of_month", "send_time")
MAX_BODY_BYTES = 32 * 1024

_LOCAL_HOST = re.compile(r"(127\.0\.0\.1|localhost)(:\d+)?")
_JSON_CONTENT_TYPE = re.compile(r"application/json\s*(;.*)?", re.IGNORECASE)


class BadRequest(Exception):
    """요청 자체가 잘못됐다(본문 형식, 길이 등). 응답 본문은 api_error 형식, 상태는 status."""

    def __init__(self, status: int, code: str, message: str) -> None:
        """상태 코드와 api_error 코드·메시지를 담는다."""
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def is_local_host(host: str) -> bool:
    """Host 헤더가 이 PC의 로컬 주소(127.0.0.1 또는 localhost, 포트는 아무거나)인지.

    DNS 리바인딩(공격자 도메인이 127.0.0.1을 가리키게 만들어 같은 출처인 척 읽기·쓰기를 시도)은 Host가
    공격자 도메인이라 여기서 걸러진다.
    """
    return _LOCAL_HOST.fullmatch(host) is not None


def check_write_origin(origin: str | None, allowed_origins: Collection[str]) -> None:
    """쓰기 요청의 Origin이 허용된 UI(정확히 그 origin)인지. 아니면(없는 경우 포함) BadRequest(403)."""
    if origin is None or origin not in allowed_origins:
        raise BadRequest(403, api_error.FORBIDDEN, "이 요청은 허용되지 않은 출처에서 왔습니다.")


def read_json_object(headers: Mapping[str, str], body: BinaryIO) -> dict[str, Any]:
    """요청 본문을 JSON 객체로 읽는다. 형식·길이·종류가 맞지 않으면 BadRequest.

    Content-Length가 필요하고(본문을 얼마나 읽을지 모르는 요청은 받지 않는다) 상한(MAX_BODY_BYTES)을 넘으면
    읽지 않고 거부한다.
    """
    if _JSON_CONTENT_TYPE.fullmatch(headers.get("Content-Type", "")) is None:
        raise BadRequest(415, api_error.INVALID_REQUEST, "본문은 application/json이어야 합니다.")
    try:
        length = int(headers.get("Content-Length", ""))
    except ValueError:
        raise BadRequest(411, api_error.INVALID_REQUEST, "Content-Length가 필요합니다.") from None
    if not 0 < length <= MAX_BODY_BYTES:
        raise BadRequest(413, api_error.INVALID_REQUEST, f"본문은 1~{MAX_BODY_BYTES}바이트여야 합니다.")
    raw = body.read(length)
    if len(raw) != length:  # 본문을 다 보내기 전에 연결을 끊었다
        raise BadRequest(400, api_error.INVALID_REQUEST, "본문이 Content-Length보다 짧습니다.")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):  # 깊이 중첩된 JSON은 RecursionError로 온다
        raise BadRequest(400, api_error.INVALID_REQUEST, "본문이 올바른 JSON이 아닙니다.") from None
    if not isinstance(parsed, dict):
        raise BadRequest(400, api_error.INVALID_REQUEST, "본문은 JSON 객체여야 합니다.")
    return parsed


def reject_body(headers: Mapping[str, str]) -> None:
    """본문이 없어야 하는 요청(DELETE)에 본문이나 Content-Type이 있으면 BadRequest(400)."""
    length = headers.get("Content-Length", "0").strip()
    if length not in ("", "0") or "Content-Type" in headers or "Transfer-Encoding" in headers:
        raise BadRequest(400, api_error.INVALID_REQUEST, "이 요청에는 본문을 보낼 수 없습니다.")


def goal_fields(body: dict[str, Any]) -> dict[str, Any]:
    """본문에서 목표 입력 다섯 칸을 꺼낸다. 모르는 칸이 있으면 BadRequest. 빠진 칸은 None으로 두어
    goals.validate_goal이 "형식이 틀렸다"고 칸별로 알리게 한다."""
    unknown = sorted(set(body) - set(GOAL_FIELDS))
    if unknown:
        raise BadRequest(400, api_error.INVALID_REQUEST, f"알 수 없는 칸이 있습니다: {', '.join(unknown)}")
    return {field: body.get(field) for field in GOAL_FIELDS}


def _fields(body: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    """본문에서 allowed 칸을 꺼낸다. 모르는 칸이 있으면 BadRequest, 빠진 칸은 None(검증이 칸별로 알린다)."""
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise BadRequest(400, api_error.INVALID_REQUEST, f"알 수 없는 칸이 있습니다: {', '.join(unknown)}")
    return {field: body.get(field) for field in allowed}


def alert_fields(body: dict[str, Any]) -> dict[str, Any]:
    """알림 규칙 입력의 다섯 칸."""
    return _fields(body, ALERT_FIELDS)


def schedule_fields(body: dict[str, Any]) -> dict[str, Any]:
    """보고서 일정 입력의 다섯 칸."""
    return _fields(body, SCHEDULE_FIELDS)


def alert_json(alert: GoalAlert) -> dict[str, Any]:
    """알림 규칙을 API 응답 모양으로."""
    return {
        "id": alert.id,
        "goal_id": alert.goal_id,
        "target_process": alert.target_process,
        "deadline": alert.deadline,
        "min_minutes": alert.min_minutes,
        "weekdays": sorted(alert.weekdays),
        "enabled": alert.enabled,
        "created_at": alert.created_at,
        "updated_at": alert.updated_at,
    }


def schedule_json(schedule: ReportSchedule) -> dict[str, Any]:
    """보고서 일정을 API 응답 모양으로. 이 PC에 저장된 설정일 뿐이고 실제 메일 발송은 서버 쪽 연결이 생길 때 붙는다(docs/goal-management.md)."""
    return {
        "goal_id": schedule.goal_id,
        "enabled": schedule.enabled,
        "frequency": schedule.frequency,
        "weekday": schedule.weekday,
        "day_of_month": schedule.day_of_month,
        "send_time": schedule.send_time,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


def goal_json(goal: Goal) -> dict[str, Any]:
    """목표를 API 응답 모양으로."""
    return {
        "id": goal.id,
        "name": goal.name,
        "daily_target_minutes": goal.daily_target_minutes,
        "weekdays": sorted(goal.weekdays),
        "processes": list(goal.processes),
        "sites": [{"browser": site.browser, "domain": site.domain} for site in goal.sites],
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


def validation_error_body(error: GoalValidationError) -> api_error.ErrorBody:
    """입력 오류를 칸별 목록과 함께 api_error 형식으로 — 화면이 칸 옆에 그대로 보여 줄 수 있다."""
    return api_error.error_body(
        api_error.INVALID_REQUEST,
        "입력을 확인해 주세요.",
        fields=[
            {"field": item.field, "code": item.code, "message": item.message} for item in error.errors
        ],
    )


def _process_time_json(time: Any) -> dict[str, Any]:
    return {"process": time.process, "active_seconds": time.active_seconds}


def _site_time_json(time: Any) -> dict[str, Any]:
    return {"browser": time.browser, "domain": time.domain, "active_seconds": time.active_seconds}


def _top_json(top: TopTarget) -> dict[str, Any]:
    """가장 길게 수행한 대상. 사이트면 site에 도메인이 있고 process는 그 사이트를 본 브라우저다."""
    return {"process": top.process, "active_seconds": top.active_seconds, "site": top.site}


def browsers_with_sites(goals: list[Goal]) -> list[str]:
    """목표들에 사이트가 연결된 브라우저 프로세스 이름들(중복 없이, 대소문자 무시) — 사이트 집계를 어느 브라우저에 돌릴지."""
    seen: dict[str, str] = {}
    for goal in goals:
        for site in goal.sites:
            seen.setdefault(site.browser.casefold(), site.browser)
    return list(seen.values())


def progress_payload(
    goals: list[Goal],
    usage: RangeUsage,
    site_usage: Mapping[str, list[Any]] | None = None,
    targets: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """구간의 사용량(usage_by_range 결과)과 목표들로 목표별 수행 시간과 요약을 만든다.

    site_usage는 브라우저 이름 → 그 브라우저의 사이트별 집계(site_usage_by_range의 by_site)다. 수행 시간의
    정의(연결한 프로세스·사이트의 활성 시간 합)는 goals.compute_progress가 갖고 있다.

    targets는 목표 id → 구간의 목표량(분)이다(`goals.period_target_minutes`). 달성률(수행 시간 ÷ 목표량)의 분모라서 목표마다 `target_minutes`로
    싣고, 요약에는 그 합을 싣는다. 목표량을 모르면(주지 않음) 0이고, 0이면 화면은 달성률을 보이지 않는다.
    """
    active = {row["process"]: row["active_seconds"] for row in usage["by_process"]}
    active_sites = {
        (browser, row["domain"]): row["active_seconds"]
        for browser, rows in (site_usage or {}).items()
        for row in rows
    }
    progress: list[GoalProgress]
    summary: ProgressSummary
    progress, summary = compute_progress(goals, active, active_sites)
    return {
        "start": usage["start"],
        "end": usage["end"],
        "goals": [
            {
                "id": item.goal_id,
                "name": item.name,
                "active_seconds": item.active_seconds,
                "processes": [_process_time_json(time) for time in item.processes],
                "sites": [_site_time_json(time) for time in item.sites],
                "target_minutes": (targets or {}).get(item.goal_id, 0),
            }
            for item in progress
        ],
        "summary": {
            "active_seconds": summary.active_seconds,
            "target_minutes": sum((targets or {}).get(item.goal_id, 0) for item in progress),
            "top": None if summary.top is None else _top_json(summary.top),
        },
    }
