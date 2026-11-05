"""저장소가 돌려주는 값 객체. 모두 읽기 전용이라 호출부가 실수로 바꿔 저장소와 어긋나지 않는다."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Goal:
    """사용자가 설정한 목표 하나.

    weekdays는 목표를 적용하는 요일이다(파이썬 date.weekday()와 같다: 월=0 … 일=6). processes는 이
    목표에 연결된 프로세스 이름들(대소문자를 구분하지 않는 이름 순)이고, 한 프로세스는 하나의 목표에만
    연결된다. created_at/updated_at은 UTC ISO 8601이다.
    """

    id: int
    name: str
    daily_target_minutes: int
    weekdays: frozenset[int]
    processes: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class GoalSnapshot:
    """어떤 날짜에 적용된 목표 설정의 기록. 목표를 나중에 바꿔도 지난 날의 달성률이 바뀌지 않게 한다.

    goal_id는 목표가 나중에 삭제돼도 남는다(과거 기록이므로 목표 테이블에 묶지 않는다).
    """

    day: date
    goal_id: int
    name: str
    daily_target_minutes: int
    processes: tuple[str, ...]
