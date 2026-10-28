"""임의 구간(start~end, UTC)에 대해 프로세스별 사용 시간을 집계한다.

recorder.db는 특정 기간을 따로 저장하지 않고 모든 틱을 계속 쌓아두기만
한다(apps/recorder/src/recorder/storage.py) — 여기서 조회 시점에 임의의
구간으로 걸러서 집계한다. 구간을 호출부가 정하게 해서("오늘"을 여기서
하드코딩하지 않음), 지금은 hub가 "최근 24시간"을 넘기지만 나중에 기간 선택
UI가 붙어도 이 함수를 그대로 재사용할 수 있다.
"""

import sqlite3
from datetime import datetime
from typing import TypedDict

# 연속된 두 틱 사이의 시간을 그 구간의 길이로 본다. 이 값보다 긴 간격은 PC
# 절전/종료나 recorder 중단으로 보고 집계에서 뺀다 — 안 그러면 잠들기 직전
# 상태가 잠들어 있던 시간 전부를 떠안아 버린다.
_MAX_GAP_SECONDS = 120.0

# seconds_since_last_input이 이 값 이상이면 그 구간 내내 idle이었다고 본다.
# 근거와 다른 툴들과 비교한 내용은 docs/2026-10-idle-threshold.md에 정리했다
# — 정답이 있는 값이 아니라 보정이 필요한 잠정값이다.
IDLE_THRESHOLD_SECONDS = 90.0


class ProcessUsage(TypedDict):
    """프로세스 하나의 구간 내 사용 시간."""

    process: str
    active_seconds: float
    """foreground였고 동시에 idle이 아니었던 시간(막대 차트의 진한 색)."""
    total_seconds: float
    """foreground(idle 포함) 또는 background로 떠 있던 시간 전체(연한 색까지 합친 총합)."""


class RangeUsage(TypedDict):
    """usage_by_range()의 반환 모양."""

    start: str
    end: str
    by_process: list[ProcessUsage]


def usage_by_range(
    conn: sqlite3.Connection,
    start: datetime,
    end: datetime,
    *,
    idle_threshold_seconds: float = IDLE_THRESHOLD_SECONDS,
) -> RangeUsage:
    """[start, end) 구간의 틱을 프로세스별 active/total 사용 시간(초)으로 집계한다.

    각 틱이 대표하는 구간의 길이는 다음 틱까지의 거리로 보고(마지막 틱은
    다음 틱이 없어 집계에서 뺀다), 그 구간 동안:
    - total_seconds: 그 틱 시점에 창이 떠 있던(tick_windowed_processes) 모든
      프로세스에 더한다 — foreground가 아니어도(background) 포함된다. 여러
      프로세스가 동시에 떠 있으면 같은 구간이 각자에게 중복으로 더해진다
      (서로 다른 프로세스의 "열려 있던 시간"이라 겹치는 게 맞다).
    - active_seconds: 그 틱의 foreground 프로세스가, idle_threshold_seconds
      이상 idle 상태가 아니었을 때만 더한다. foreground는 한 틱에 하나뿐이라
      겹치지 않는다.
    """
    start_iso, end_iso = start.isoformat(), end.isoformat()

    ticks = conn.execute(
        "SELECT ticks.id, ticks.sampled_at, processes.name, ticks.seconds_since_last_input "
        "FROM ticks LEFT JOIN processes ON processes.id = ticks.foreground_process_id "
        "WHERE ticks.sampled_at >= ? AND ticks.sampled_at < ? "
        "ORDER BY ticks.sampled_at",
        (start_iso, end_iso),
    ).fetchall()

    if len(ticks) < 2:
        return {"start": start_iso, "end": end_iso, "by_process": []}

    tick_ids = [row[0] for row in ticks]
    placeholders = ",".join("?" * len(tick_ids))
    windowed_rows = conn.execute(
        "SELECT tick_windowed_processes.tick_id, processes.name "
        "FROM tick_windowed_processes "
        "JOIN processes ON processes.id = tick_windowed_processes.process_id "
        f"WHERE tick_windowed_processes.tick_id IN ({placeholders})",
        tick_ids,
    ).fetchall()

    windowed_by_tick: dict[int, set[str]] = {}
    for tick_id, name in windowed_rows:
        windowed_by_tick.setdefault(tick_id, set()).add(name)

    active_seconds: dict[str, float] = {}
    total_seconds: dict[str, float] = {}

    for (tick_id, sampled_at, fg_name, idle_seconds), (_, next_sampled_at, _, _) in zip(
        ticks, ticks[1:]
    ):
        gap = (
            datetime.fromisoformat(next_sampled_at) - datetime.fromisoformat(sampled_at)
        ).total_seconds()
        if gap > _MAX_GAP_SECONDS:
            continue

        for name in windowed_by_tick.get(tick_id, ()):
            total_seconds[name] = total_seconds.get(name, 0.0) + gap

        if fg_name is not None and idle_seconds < idle_threshold_seconds:
            active_seconds[fg_name] = active_seconds.get(fg_name, 0.0) + gap

    names = set(active_seconds) | set(total_seconds)
    by_process: list[ProcessUsage] = [
        {
            "process": name,
            "active_seconds": active_seconds.get(name, 0.0),
            "total_seconds": total_seconds.get(name, 0.0),
        }
        for name in names
    ]
    by_process.sort(key=lambda row: -row["total_seconds"])

    return {"start": start_iso, "end": end_iso, "by_process": by_process}
