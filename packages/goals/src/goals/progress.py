"""목표별 수행 시간 — "연결한 프로세스의 활성 시간 합"이라는 정의의 유일한 원본.

화면(홈 요약)·서버로 보낼 달성 수치·메일 리포트가 같은 뜻의 숫자를 쓰도록, 계산을 여기 한곳에 둔다.
입력은 목표 목록과 "프로세스 이름 → 구간의 활성(active) 시간(초)"이다(aggregation의 usage_by_range
결과에서 뽑는다) — 이 패키지는 기록 DB를 읽지 않는다.

정의:
- 목표의 수행 시간 = 그 목표에 연결된 프로세스들의 활성 시간 합(유휴·백그라운드는 세지 않는다).
- 요일은 곱하지 않는다: 어느 요일에 쌓인 시간이든 구간 안의 연결 프로세스 활성 시간을 센다(요일은
  목표량 계산에만 쓰인다 — 달성률은 이 패키지의 다음 단계).
- 한 프로세스는 하나의 목표에만 연결돼 있어서(저장소가 보장) 같은 시간이 두 번 세어지지 않는다.
- 프로세스 이름은 대소문자를 구분하지 않고 맞춰 본다(process_key).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from goals.models import Goal
from goals.validation import process_key


@dataclass(frozen=True)
class ProcessTime:
    """프로세스 하나의 활성 시간(초)."""

    process: str
    active_seconds: float


@dataclass(frozen=True)
class GoalProgress:
    """목표 하나의 수행 시간. processes는 연결된 프로세스 전부(시간이 0이어도)를 연결 목록 순서로 담는다."""

    goal_id: int
    name: str
    active_seconds: float
    processes: tuple[ProcessTime, ...]


@dataclass(frozen=True)
class ProgressSummary:
    """모든 목표를 합친 요약. top은 연결된 프로세스 중 활성 시간이 가장 긴 것(전부 0이면 None)."""

    active_seconds: float
    top: ProcessTime | None


def compute_progress(
    goals: Sequence[Goal], active_seconds_by_process: Mapping[str, float]
) -> tuple[list[GoalProgress], ProgressSummary]:
    """목표들의 수행 시간과 전체 요약을 계산한다.

    active_seconds_by_process의 키는 기록된 프로세스 이름이다. 대소문자만 다른 이름이 따로 기록돼
    있으면(Windows 파일 이름은 대소문자를 구분하지 않는다) 같은 프로세스로 보고 합친다. 시간이 같은
    프로세스끼리는 이름(대소문자 무시) 순서로 먼저 오는 쪽이 top이다.
    """
    seconds_by_key: dict[str, float] = {}
    for name, seconds in active_seconds_by_process.items():
        key = process_key(name)
        seconds_by_key[key] = seconds_by_key.get(key, 0.0) + seconds

    progress: list[GoalProgress] = []
    for goal in goals:
        times = tuple(
            ProcessTime(process, seconds_by_key.get(process_key(process), 0.0))
            for process in goal.processes
        )
        progress.append(
            GoalProgress(
                goal_id=goal.id,
                name=goal.name,
                active_seconds=sum(time.active_seconds for time in times),
                processes=times,
            )
        )

    all_times = [time for item in progress for time in item.processes]
    # 밀리초로 반올림해 비교한다(float 합 오차로 동률 판정이 깨지지 않게 — aggregation과 같은 이유).
    ranked = sorted(all_times, key=lambda time: (-round(time.active_seconds, 3), process_key(time.process)))
    top = ranked[0] if ranked and ranked[0].active_seconds > 0 else None
    return progress, ProgressSummary(
        active_seconds=sum(item.active_seconds for item in progress), top=top
    )
