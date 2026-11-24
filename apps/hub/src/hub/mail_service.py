"""보고서 메일 구독 요청의 입력 모양(hub). 값의 규칙(주기·요일·일자·시각·시간대)은 서버가 검증하므로 여기서는 **모양만** 본다 — 규칙을 두 곳에
두면 어긋난다. 이 PC의 목표 id를 서버 목표 id로 바꾸는 것은 `cloud_adapter`가 한다(서버 id는 화면에 나가지 않는다).
"""

from typing import Any

from common import api_error

from hub.goals_service import BadRequest

FREQUENCIES = ("daily", "weekly", "monthly")
_FIELDS = {"goal_id", "frequency", "weekday", "day_of_month", "send_time", "timezone", "replace"}


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def subscription_request(body: dict[str, Any]) -> dict[str, Any]:
    """`PUT /api/mail/subscription`의 본문. goal_id는 이 PC의 목표 id다."""
    extra = sorted(set(body) - _FIELDS)
    if extra:
        raise BadRequest(400, api_error.INVALID_REQUEST, f"알 수 없는 칸이 있습니다: {', '.join(extra)}")
    goal_id = body.get("goal_id")
    if not _int(goal_id) or goal_id < 1:
        raise BadRequest(400, api_error.INVALID_REQUEST, "goal_id는 이 PC의 목표 번호여야 합니다.")
    frequency = body.get("frequency")
    if frequency not in FREQUENCIES:
        raise BadRequest(400, api_error.INVALID_REQUEST, "frequency는 daily·weekly·monthly 중 하나여야 합니다.")
    weekday = body.get("weekday")
    day_of_month = body.get("day_of_month")
    if weekday is not None and not _int(weekday):
        raise BadRequest(400, api_error.INVALID_REQUEST, "weekday는 정수여야 합니다.")
    if day_of_month is not None and not _int(day_of_month):
        raise BadRequest(400, api_error.INVALID_REQUEST, "day_of_month는 정수여야 합니다.")
    send_time, timezone = body.get("send_time"), body.get("timezone")
    if not isinstance(send_time, str) or not isinstance(timezone, str) or len(timezone) > 64:
        raise BadRequest(400, api_error.INVALID_REQUEST, "send_time과 timezone은 글자여야 합니다.")
    replace = body.get("replace", False)
    if not isinstance(replace, bool):
        raise BadRequest(400, api_error.INVALID_REQUEST, "replace는 true 또는 false여야 합니다.")
    return {
        "goal_id": goal_id,
        "frequency": frequency,
        "weekday": weekday,
        "day_of_month": day_of_month,
        "send_time": send_time,
        "timezone": timezone,
        "replace": replace,
    }


def status_request(body: dict[str, Any]) -> str:
    """`POST /api/mail/subscription/status`의 본문 `{status: "active" | "paused"}`."""
    if set(body) != {"status"} or body["status"] not in ("active", "paused"):
        raise BadRequest(400, api_error.INVALID_REQUEST, "status는 active 또는 paused여야 합니다.")
    return body["status"]
