"""한 틱에서 관찰할 값들을 한 번에 묶어서 가져온다.

sample_tick()은 순수 함수다 — DB나 누적 상태를 전혀 건드리지 않고, 그 순간의
값을 읽어서 반환만 한다. 저장(side effect)은 호출부의 책임이다
(docs/recorder-sqlite-design.md의 "틱 처리 구조" 참고).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from recorder.input_activity import get_seconds_since_last_input
from recorder.window_snapshot import (
    get_foreground_process_name,
    get_windowed_process_names,
)


@dataclass(frozen=True)
class TickSample:
    """한 틱에서 관찰한 값들의 불변 스냅샷. storage.save_tick()이 그대로 저장한다."""

    sampled_at: datetime
    foreground_process: str | None
    windowed_processes: frozenset[str]
    seconds_since_last_input: float


def sample_tick() -> TickSample:
    """지금 이 순간의 FG/창 목록/입력 idle 시간을 한 번에 읽어서 묶어 반환한다."""
    return TickSample(
        sampled_at=datetime.now(UTC),
        foreground_process=get_foreground_process_name(),
        windowed_processes=frozenset(get_windowed_process_names()),
        seconds_since_last_input=get_seconds_since_last_input(),
    )
