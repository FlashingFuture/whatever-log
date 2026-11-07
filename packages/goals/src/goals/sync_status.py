"""동기화 상태: 에이전트가 주기마다 결과를 적고, 화면(hub)이 읽어 "잘 되고 있는지"를 알려 준다.

서버를 부르지 않고 `goals.db`의 값만 다루는 로컬 로직이라 `goals`에 둔다(`cloud`·`goalsync`가 깨져도 hub가 상태를 읽을 수 있게).

`goals.db`의 `sync_meta`에 JSON 한 줄(`sync_status`)로 둔다. hub와 에이전트가 이미 함께 쓰는 DB라 경로 설정이 늘지 않고, 한 줄이라 쓰는
도중에 읽어도 반쪽짜리 값을 보지 않는다. 계정이 바뀌어 연결을 끊을 때(`reset_sync`)는 함께 지워진다.

상태에는 **목표 이름·프로세스·토큰이 들어가지 않는다.** 개수와 오류의 종류만 있다(사용자에게 보여 주는 문장은 읽는 쪽이 종류로 만든다).
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from goals.store import GoalStore

META_STATUS = "sync_status"

# 마지막 시도의 결과 종류. ok 외에는 "왜 안 됐는지"의 분류다.
RESULT_OK = "ok"
RESULT_SIGNED_OUT = "signed_out"  # 로그인되어 있지 않아 건너뜀(오류 아님)
RESULT_NOT_ENABLED = "not_enabled"  # 사용자가 아직 동기화를 켜지 않아 건너뜀(오류 아님)
RESULT_ACCOUNT_CHANGED = "account_changed"  # 다른 계정이라 연결을 끊음(다시 확인이 필요하다)
RESULT_UNREACHABLE = "unreachable"
RESULT_NOT_AUTHORIZED = "not_authorized"
RESULT_SERVER_ERROR = "server_error"
RESULT_INTERNAL = "internal"

# 오류로 보는 결과들(화면이 빨간 안내를 띄운다).
ERROR_RESULTS = frozenset({RESULT_UNREACHABLE, RESULT_NOT_AUTHORIZED, RESULT_SERVER_ERROR, RESULT_INTERNAL})

# 에이전트가 이 배수만큼의 주기 동안 아무 기록도 남기지 않으면 "실행 중이 아님"으로 본다(주기가 늘어나는 백오프도 감안한다).
STALE_AFTER_INTERVALS = 3
MIN_STALE_SECONDS = 120.0


@dataclass(frozen=True)
class StatusRecord:
    """에이전트가 마지막으로 적은 것."""

    at: str  # 마지막 시도 시각(UTC ISO)
    result: str  # RESULT_*
    last_success_at: str | None  # 마지막으로 성공한 시각
    problems: int  # 이번 주기의 문제 건수(올리지 못한 목표 등)
    interval: float  # 에이전트의 주기(초) — 실행 중인지 판단하는 기준


def record(
    store: GoalStore,
    *,
    result: str,
    problems: int,
    interval: float,
    now: datetime | None = None,
) -> StatusRecord:
    """이번 시도의 결과를 적는다. 성공(`ok`·건너뜀 아님)이면 마지막 성공 시각을 갱신하고, 아니면 이전 값을 유지한다."""
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    previous = read_record(store)
    success = stamp if result == RESULT_OK else (previous.last_success_at if previous else None)
    current = StatusRecord(at=stamp, result=result, last_success_at=success, problems=problems, interval=interval)
    store.set_meta(META_STATUS, json.dumps(asdict(current)))
    return current


def read_record(store: GoalStore) -> StatusRecord | None:
    """적혀 있는 상태. 없거나 형식이 깨졌으면 None(읽는 쪽이 "아직 한 번도 안 돎"으로 본다)."""
    raw = store.get_meta(META_STATUS)
    if raw is None:
        return None
    try:
        data: dict[str, Any] = json.loads(raw)
        return StatusRecord(
            at=str(data["at"]),
            result=str(data["result"]),
            last_success_at=None if data.get("last_success_at") is None else str(data["last_success_at"]),
            problems=int(data["problems"]),
            interval=float(data["interval"]),
        )
    except (ValueError, KeyError, TypeError):
        return None


# 화면이 보여 주는 상태.
STATE_OFF = "off"  # 동기화를 켜지 않음
STATE_WAITING = "waiting"  # 켰지만 에이전트가 아직 한 번도 돌지 않음
STATE_OK = "ok"
STATE_ERROR = "error"
STATE_STALE = "stale"  # 켰는데 에이전트가 한동안 돌지 않음


def _parse(stamp: str | None) -> datetime | None:
    if stamp is None:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def describe(record_: StatusRecord | None, *, enabled: bool, now: datetime) -> dict[str, Any]:
    """화면에 줄 상태. state 하나로 그림을 정하고, 나머지는 설명에 쓴다. 이름·토큰은 없다.

    - 동기화를 켜지 않았으면 `off`(에이전트가 돌든 말든 상관없다).
    - 켰는데 기록이 없으면 `waiting`, 마지막 기록이 `interval`의 몇 배보다 오래됐으면 `stale`(에이전트가 꺼져 있다).
    - 마지막 시도가 오류면 `error`(`result`가 종류), 아니면 `ok`(건너뜀 결과도 오류는 아니다).
    """
    base: dict[str, Any] = {
        "enabled": enabled,
        "state": STATE_OFF,
        "result": None,
        "last_attempt_at": None,
        "last_success_at": None,
        "problems": 0,
    }
    if not enabled:
        return base
    if record_ is None:
        return {**base, "state": STATE_WAITING}
    base.update(
        result=record_.result,
        last_attempt_at=record_.at,
        last_success_at=record_.last_success_at,
        problems=record_.problems,
    )
    attempted = _parse(record_.at)
    limit = max(MIN_STALE_SECONDS, record_.interval * STALE_AFTER_INTERVALS)
    if attempted is None or (now - attempted).total_seconds() > limit:
        return {**base, "state": STATE_STALE}
    return {**base, "state": STATE_ERROR if record_.result in ERROR_RESULTS else STATE_OK}
