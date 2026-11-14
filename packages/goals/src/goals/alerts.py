"""목표의 알림 규칙과 보고서 일정 — 값 객체, 입력 검증, "지금 알려야 할 알림" 판단 (docs/goal-management.md).

목표 설정과 같은 원칙으로 일부러 엄격하다: 모양이 조금이라도 다르면 조용히 고쳐 받지 않고 칸별 오류로 거부하고, 이 모듈이 규칙의 유일한 원본이다
(화면의 즉시 안내는 편의일 뿐). 저장은 `GoalStore`가 하고, 여기는 기록 DB도 시계도 모른다 — 판단에 필요한 값(지금 시각, 목표별 오늘 수행 시간,
이미 알린 기록)을 받아 계산만 하므로 테스트가 쉽다.

알림 규칙: "마감 시각(HH:MM)까지 대상의 오늘 활성 시간이 N분 이상이 되지 않으면 알린다."
- 대상은 목표 전체(연결한 프로세스·사이트의 활성 시간 합 = 목표 수행 시간)이거나, 그 목표에 연결한 프로세스 하나다(예: 출석 체크가 필요한 게임).
- 적용 요일을 정할 수 있고, 같은 규칙은 **하루에 한 번만** 알린다(`goal_alert_log`).
- 규칙을 마감 시각이 이미 지난 뒤에 만들었다면 그날은 건너뛴다(만들자마자 알림이 뜨는 일을 막는다).

보고서 일정: "매일/매주 요일/매달 일자의 HH:MM에 이 목표의 보고서를 메일로 보낸다"는 **설정**이다. 실제 발송은 서버가 하고(아직 연결되지 않았다)
이 PC에는 설정만 저장한다.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from goals.errors import FieldError, GoalValidationError
from goals.models import Goal
from goals.validation import _check_weekdays, _is_plain_int, process_key

MAX_ALERTS_PER_GOAL = 10
MIN_ALERT_MINUTES = 1
MAX_ALERT_MINUTES = 24 * 60

FREQUENCIES = ("daily", "weekly", "monthly")
# 매달 일자는 28일까지만 받는다 — 29~31일은 없는 달이 있어 "그 달에는 안 간다"는 모호함이 생긴다.
MAX_DAY_OF_MONTH = 28

_TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


@dataclass(frozen=True)
class GoalAlert:
    """알림 규칙 하나. target_process가 None이면 목표 전체가 대상이다."""

    id: int
    goal_id: int
    target_process: str | None
    deadline: str
    min_minutes: int
    weekdays: frozenset[int]
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AlertSpec:
    """검증을 통과한 알림 입력. 저장소는 이 값만 받는다."""

    target_process: str | None
    target_key: str | None
    deadline: str
    min_minutes: int
    weekdays: frozenset[int]
    enabled: bool


@dataclass(frozen=True)
class ReportSchedule:
    """목표 하나의 보고서 메일 일정(설정). weekday는 weekly일 때만, day_of_month는 monthly일 때만 있다."""

    goal_id: int
    enabled: bool
    frequency: str
    weekday: int | None
    day_of_month: int | None
    send_time: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ScheduleSpec:
    """검증을 통과한 보고서 일정 입력."""

    enabled: bool
    frequency: str
    weekday: int | None
    day_of_month: int | None
    send_time: str


def _check_time(field: str, label: str, value: Any, errors: list[FieldError]) -> str | None:
    """`HH:MM`(24시간, 0 채움) 칸을 검사한다."""
    if not isinstance(value, str):
        errors.append(FieldError(field, "type", f"{label}은 `HH:MM` 문자열이어야 합니다."))
        return None
    if _TIME.fullmatch(value) is None:
        errors.append(FieldError(field, "format", f"{label}은 00:00~23:59의 `HH:MM` 형식이어야 합니다."))
        return None
    return value


def _check_enabled(value: Any, errors: list[FieldError]) -> bool | None:
    if not isinstance(value, bool):
        errors.append(FieldError("enabled", "type", "켜짐 여부는 true/false여야 합니다."))
        return None
    return value


def validate_alert(
    *,
    target_process: Any,
    deadline: Any,
    min_minutes: Any,
    weekdays: Any,
    enabled: Any,
    linked_processes: Collection[str],
) -> AlertSpec:
    """알림 입력을 검증한다. 통과하면 AlertSpec, 아니면 모든 칸의 오류를 모아 GoalValidationError.

    target_process는 None(목표 전체)이거나 **그 목표에 연결한 프로세스**여야 한다(대소문자 무시). 연결하지 않은 프로세스를 대상으로 하면
    수행 시간이 영원히 0이라 매일 알림이 뜨는 규칙이 되기 때문이다.
    """
    errors: list[FieldError] = []
    target_key: str | None = None
    target: str | None = None
    if target_process is not None:
        if not isinstance(target_process, str):
            errors.append(FieldError("target_process", "type", "대상은 프로세스 이름(문자열)이거나 비워 두어야 합니다."))
        else:
            wanted = process_key(target_process)
            match = next((name for name in linked_processes if process_key(name) == wanted), None)
            if match is None:
                errors.append(FieldError("target_process", "not_linked", "이 목표에 연결한 프로세스만 대상으로 고를 수 있습니다."))
            else:
                target, target_key = match, wanted
    checked_deadline = _check_time("deadline", "마감 시각", deadline, errors)
    minutes: int | None = None
    if not _is_plain_int(min_minutes):
        errors.append(FieldError("min_minutes", "type", "최소 시간은 정수(분)여야 합니다."))
    elif not MIN_ALERT_MINUTES <= min_minutes <= MAX_ALERT_MINUTES:
        errors.append(
            FieldError("min_minutes", "range", f"최소 시간은 {MIN_ALERT_MINUTES}~{MAX_ALERT_MINUTES}분이어야 합니다.")
        )
    else:
        minutes = min_minutes
    checked_weekdays = _check_weekdays(weekdays, errors)
    checked_enabled = _check_enabled(enabled, errors)
    if errors or checked_deadline is None or minutes is None or checked_weekdays is None or checked_enabled is None:
        raise GoalValidationError(errors)
    return AlertSpec(target, target_key, checked_deadline, minutes, checked_weekdays, checked_enabled)


def validate_schedule(
    *, enabled: Any, frequency: Any, weekday: Any, day_of_month: Any, send_time: Any
) -> ScheduleSpec:
    """보고서 일정 입력을 검증한다. weekday는 weekly일 때만 필수(아니면 None), day_of_month는 monthly일 때만 필수(아니면 None)."""
    errors: list[FieldError] = []
    checked_enabled = _check_enabled(enabled, errors)
    checked_time = _check_time("send_time", "보낼 시각", send_time, errors)
    checked_weekday: int | None = None
    checked_day: int | None = None
    if frequency not in FREQUENCIES:
        errors.append(FieldError("frequency", "choice", f"주기는 {', '.join(FREQUENCIES)} 중 하나여야 합니다."))
    elif frequency == "weekly":
        if not _is_plain_int(weekday) or not 0 <= weekday <= 6:
            errors.append(FieldError("weekday", "range", "매주 보낼 요일은 0(월)~6(일)이어야 합니다."))
        else:
            checked_weekday = weekday
        if day_of_month is not None:
            errors.append(FieldError("day_of_month", "unexpected", "매주 보내는 일정에는 일자를 정할 수 없습니다."))
    elif frequency == "monthly":
        if not _is_plain_int(day_of_month) or not 1 <= day_of_month <= MAX_DAY_OF_MONTH:
            errors.append(FieldError("day_of_month", "range", f"매달 보낼 일자는 1~{MAX_DAY_OF_MONTH}일이어야 합니다."))
        else:
            checked_day = day_of_month
        if weekday is not None:
            errors.append(FieldError("weekday", "unexpected", "매달 보내는 일정에는 요일을 정할 수 없습니다."))
    else:  # daily
        if weekday is not None:
            errors.append(FieldError("weekday", "unexpected", "매일 보내는 일정에는 요일을 정할 수 없습니다."))
        if day_of_month is not None:
            errors.append(FieldError("day_of_month", "unexpected", "매일 보내는 일정에는 일자를 정할 수 없습니다."))
    if errors or checked_enabled is None or checked_time is None:
        raise GoalValidationError(errors)
    return ScheduleSpec(checked_enabled, frequency, checked_weekday, checked_day, checked_time)


@dataclass(frozen=True)
class DueAlert:
    """지금 알려야 할 알림 하나. active_minutes는 대상의 오늘 활성 시간(분, 내림)이다."""

    alert: GoalAlert
    goal_name: str
    active_minutes: int


def _parse_time(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def due_alerts(
    alerts: Collection[GoalAlert],
    goals: Collection[Goal],
    *,
    now: datetime,
    seconds_by_process: Mapping[str, float],
    goal_seconds: Mapping[int, float],
    already_fired: Collection[int],
) -> list[DueAlert]:
    """지금(now, 이 PC의 시간대로 시간이 붙은 시각) 알려야 할 알림들.

    알리는 조건은 모두 만족해야 한다: 켜져 있다 / 오늘이 적용 요일이다 / 마감 시각이 지났다 / 오늘 아직 알리지 않았다 / 규칙을 마감 시각 전에 만들었다 /
    대상의 오늘 활성 시간이 최소 시간 미만이다. 목표가 지워졌거나 대상 프로세스를 목표에서 뺐다면(연결이 끊겼다) 건너뛴다.

    seconds_by_process는 기록된 프로세스 이름 → 오늘 활성 시간(초), goal_seconds는 목표 id → 오늘 목표 수행 시간(초, `goals.compute_progress`의
    결과)이다. 프로세스 이름은 대소문자를 구분하지 않고 맞춰 본다.
    """
    if now.tzinfo is None:
        raise ValueError("now는 시간대가 있는 시각이어야 합니다.")
    today: date = now.date()
    by_goal = {goal.id: goal for goal in goals}
    process_seconds: dict[str, float] = {}
    for name, seconds in seconds_by_process.items():
        key = process_key(name)
        process_seconds[key] = process_seconds.get(key, 0.0) + seconds
    fired = set(already_fired)

    due: list[DueAlert] = []
    for alert in alerts:
        goal = by_goal.get(alert.goal_id)
        if goal is None or not alert.enabled or alert.id in fired:
            continue
        if today.weekday() not in alert.weekdays:
            continue
        deadline = datetime.combine(today, _parse_time(alert.deadline), tzinfo=now.tzinfo)
        if now < deadline:
            continue
        created = datetime.fromisoformat(alert.created_at).astimezone(now.tzinfo)
        if created > deadline:  # 마감이 지난 뒤에 만든 규칙은 그날은 건너뛴다
            continue
        if alert.target_process is None:
            seconds = goal_seconds.get(goal.id, 0.0)
        else:
            if all(process_key(name) != process_key(alert.target_process) for name in goal.processes):
                continue
            seconds = process_seconds.get(process_key(alert.target_process), 0.0)
        if seconds < alert.min_minutes * 60:
            due.append(DueAlert(alert, goal.name, int(seconds // 60)))
    return due
