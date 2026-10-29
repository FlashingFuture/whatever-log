"""임의 구간(start~end)에 대해 프로세스별 사용 시간을 집계한다.

recorder.db는 특정 기간을 따로 저장하지 않고 모든 틱을 계속 쌓아두기만
한다(apps/recorder/src/recorder/storage.py) — 여기서 조회 시점에 임의의
구간으로 걸러서 집계한다. "오늘/이번 주" 같은 경계는 호출부가 정한다(지금은
apps/ui가 로컬 타임존 기준으로 계산해서 hub에 넘긴다).
"""

import sqlite3
from datetime import UTC, datetime
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
    """프로세스 하나의 구간 내 사용 시간. 세 값은 서로 겹치지 않고
    active_seconds + idle_seconds + background_seconds == total_seconds다."""

    process: str
    active_seconds: float
    """foreground였고 동시에 idle이 아니었던 시간."""
    idle_seconds: float
    """foreground였지만 idle_threshold_seconds 이상 입력이 없었던(idle) 시간."""
    background_seconds: float
    """foreground가 아니었지만 창이 떠 있던(background) 시간."""
    total_seconds: float
    """위 세 값의 합."""


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
    """[start, end) 구간의 틱을 프로세스별 active/idle/background 시간(초)으로 집계한다.

    각 틱이 대표하는 구간의 길이는 다음 틱까지의 거리로 보고(마지막 틱은
    다음 틱이 없어 집계에서 뺀다), 그 구간 동안 틱 시점에 열려 있던 각
    프로세스를 아래 셋 중 **정확히 하나**로 분류한다(겹치지 않음):

    - active_seconds: 그 틱의 foreground 프로세스였고, idle_threshold_seconds
      이상 idle 상태가 아니었다.
    - idle_seconds: 그 틱의 foreground 프로세스였지만, idle_threshold_seconds
      이상 idle 상태였다.
    - background_seconds: foreground가 아니었지만 창이 떠 있었다
      (tick_windowed_processes). 여러 프로세스가 동시에 떠 있으면 같은
      구간이 각자에게 중복으로 더해진다(서로 다른 프로세스의 "열려 있던
      시간"이라 겹치는 게 맞다).
    """
    # sampled_at은 UTC ISO 문자열로 저장돼 있고 문자열로 비교한다 — 경계도
    # 같은 UTC 표기로 맞춰야 한다. +09:00 같은 오프셋이 붙은 채로 비교하면
    # 같은 시각이어도 문자열 순서가 달라져 조용히 틀린 구간이 잡힌다.
    start_iso = start.astimezone(UTC).isoformat()
    end_iso = end.astimezone(UTC).isoformat()

    ticks = conn.execute(
        "SELECT ticks.id, ticks.sampled_at, processes.name, ticks.seconds_since_last_input "
        "FROM ticks LEFT JOIN processes ON processes.id = ticks.foreground_process_id "
        "WHERE ticks.sampled_at >= ? AND ticks.sampled_at < ? "
        "ORDER BY ticks.sampled_at",
        (start_iso, end_iso),
    ).fetchall()

    if len(ticks) < 2:
        return {"start": start_iso, "end": end_iso, "by_process": []}

    # 틱 id를 모아서 IN (...)에 바인딩하지 않는다 — recorder는 --interval 1초도
    # 허용하는데, 그 간격으로 24시간이면 틱이 8만 개를 넘어 SQLite의 파라미터
    # 개수 한도(기본 32766개)를 넘길 수 있다. 대신 틱과 같은 sampled_at 범위로
    # 직접 조인한다.
    windowed_rows = conn.execute(
        "SELECT tick_windowed_processes.tick_id, processes.name "
        "FROM tick_windowed_processes "
        "JOIN processes ON processes.id = tick_windowed_processes.process_id "
        "JOIN ticks ON ticks.id = tick_windowed_processes.tick_id "
        "WHERE ticks.sampled_at >= ? AND ticks.sampled_at < ?",
        (start_iso, end_iso),
    ).fetchall()

    windowed_by_tick: dict[int, set[str]] = {}
    for tick_id, name in windowed_rows:
        windowed_by_tick.setdefault(tick_id, set()).add(name)

    active_seconds: dict[str, float] = {}
    idle_seconds: dict[str, float] = {}
    background_seconds: dict[str, float] = {}

    for (tick_id, sampled_at, fg_name, since_last_input), (_, next_sampled_at, _, _) in zip(
        ticks, ticks[1:]
    ):
        gap = (
            datetime.fromisoformat(next_sampled_at) - datetime.fromisoformat(sampled_at)
        ).total_seconds()
        if gap > _MAX_GAP_SECONDS:
            continue

        # get_foreground_process_name()과 get_windowed_process_names()는
        # 서로 독립적으로 조회된다(window_snapshot.py) — 제목 없는 foreground
        # 창은 창 목록 필터(GetWindowTextLengthW == 0 제외)에서 빠질 수 있다.
        # foreground를 열려 있던 프로세스 집합에 직접 합쳐야 누락 없이 active/idle
        # 로 분류된다.
        open_names = windowed_by_tick.get(tick_id, set())
        if fg_name is not None:
            open_names = open_names | {fg_name}

        for name in open_names:
            if name == fg_name:
                bucket = active_seconds if since_last_input < idle_threshold_seconds else idle_seconds
            else:
                bucket = background_seconds
            bucket[name] = bucket.get(name, 0.0) + gap

    names = set(active_seconds) | set(idle_seconds) | set(background_seconds)
    by_process: list[ProcessUsage] = []
    for name in names:
        active = active_seconds.get(name, 0.0)
        idle = idle_seconds.get(name, 0.0)
        background = background_seconds.get(name, 0.0)
        by_process.append(
            {
                "process": name,
                "active_seconds": active,
                "idle_seconds": idle,
                "background_seconds": background,
                "total_seconds": active + idle + background,
            }
        )
    by_process.sort(key=lambda row: -row["total_seconds"])

    return {"start": start_iso, "end": end_iso, "by_process": by_process}
