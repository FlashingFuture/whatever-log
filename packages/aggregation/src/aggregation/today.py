"""오늘(로컬 날짜 기준) 사용 현황을 프로세스별로 집계한다.

recorder.db는 "오늘"을 따로 저장하지 않고 모든 틱을 계속 쌓아두기만
한다(apps/recorder/src/recorder/storage.py) — 여기서 조회 시점에 로컬
날짜 범위로 걸러서 집계한다.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TypedDict

# 연속된 두 틱 사이의 시간을 그 구간 동안 foreground였던 프로세스의 사용
# 시간으로 본다. 이 값보다 긴 간격은 PC 절전/종료나 recorder 중단으로 보고
# 집계에서 뺀다 — 안 그러면 잠들기 직전 포커스였던 프로세스가 잠들어 있던
# 시간 전부를 "사용 시간"으로 가져가 버린다.
_MAX_GAP_SECONDS = 120.0


class ProcessUsage(TypedDict):
    """프로세스 하나의 오늘 foreground 사용 시간."""

    process: str
    seconds: float


class TodayUsage(TypedDict):
    """today_usage()의 반환 모양. apps/hub가 그대로 JSON으로 응답한다.

    apps/ui(TS) 쪽에도 같은 모양의 interface가 따로 있다 — 지금은 엔드포인트
    하나뿐이라 언어 경계를 넘어 스키마를 공유하는 인프라(codegen 등)를 들일
    정도는 아니라고 보고, 당장은 각자 유지한다. 엔드포인트가 늘어나거나
    모양이 복잡해지면 JSON Schema 같은 공유 스펙을 두는 걸 고려한다.
    """

    date: str
    total_seconds: float
    by_process: list[ProcessUsage]


def _local_day_bounds_utc(now: datetime) -> tuple[str, str]:
    """now가 속한 로컬 날짜의 자정~다음 자정을 UTC ISO 문자열 경계로 바꾼다.

    sampled_at은 UTC로 저장되는데 "오늘"은 로컬 날짜 기준이어야 해서, 자정
    경계를 로컬 타임존에서 잡은 뒤 UTC로 바꾼다 — UTC 기준으로 그냥 자르면
    자정 근처 틱이 하루 어긋나게 집계된다.
    """
    local_now = now.astimezone()
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    return (
        local_start.astimezone(UTC).isoformat(),
        local_end.astimezone(UTC).isoformat(),
    )


def today_usage(conn: sqlite3.Connection, *, now: datetime | None = None) -> TodayUsage:
    """오늘 기록된 틱을 foreground 프로세스별 사용 시간(초)으로 집계해서 반환한다.

    각 틱이 대표하는 구간의 길이는 알 수 없으므로(간격은 설정에 따라
    다르다), 연속한 두 틱의 sampled_at 차이를 그 구간의 길이로 쓴다. 마지막
    틱은 다음 틱이 없어 구간을 알 수 없으므로 집계에서 뺀다.
    """
    now = now or datetime.now(UTC)
    start_utc, end_utc = _local_day_bounds_utc(now)

    rows = conn.execute(
        "SELECT ticks.sampled_at, processes.name "
        "FROM ticks LEFT JOIN processes ON processes.id = ticks.foreground_process_id "
        "WHERE ticks.sampled_at >= ? AND ticks.sampled_at < ? "
        "ORDER BY ticks.sampled_at",
        (start_utc, end_utc),
    ).fetchall()

    seconds_by_process: dict[str, float] = {}
    for (sampled_at, name), (next_sampled_at, _next_name) in zip(rows, rows[1:]):
        if name is None:
            continue
        gap = (
            datetime.fromisoformat(next_sampled_at) - datetime.fromisoformat(sampled_at)
        ).total_seconds()
        if gap > _MAX_GAP_SECONDS:
            continue
        seconds_by_process[name] = seconds_by_process.get(name, 0.0) + gap

    by_process = [
        {"process": name, "seconds": seconds}
        for name, seconds in sorted(seconds_by_process.items(), key=lambda kv: -kv[1])
    ]
    return {
        "date": now.astimezone().date().isoformat(),
        "total_seconds": sum(seconds_by_process.values()),
        "by_process": by_process,
    }
