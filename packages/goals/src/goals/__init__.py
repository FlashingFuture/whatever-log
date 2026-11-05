"""목표와 연결 프로세스의 모델·검증·저장.

이 패키지가 "목표가 무엇이고 무엇이 올바른 입력인지"의 유일한 원본이다. 화면은 입력을 받아 보여 줄
뿐이고, hub(/api/goals)와 나중의 전송 에이전트가 같은 코드를 그대로 쓴다. 목표와 연결 정보는
사용자의 PC에만 있고 서버로 보내지 않는다(docs/data-handling.md) — 서버로는 목표별 달성 수치만 간다.

- models: Goal, GoalSnapshot (읽기 전용 값 객체)
- validation: 입력 검증(엄격). 규칙의 상수도 여기 있다
- store: goals.db(SQLite) 저장소 — CRUD와 하루 스냅샷
- errors: 검증·조회 실패
"""

from goals.errors import FieldError, GoalNotFoundError, GoalValidationError, SchemaVersionError
from goals.models import Goal, GoalSnapshot
from goals.store import GoalStore
from goals.validation import (
    MAX_GOALS,
    MAX_PROCESSES_PER_GOAL,
    process_key,
    validate_goal,
)

__all__ = [
    "MAX_GOALS",
    "MAX_PROCESSES_PER_GOAL",
    "FieldError",
    "Goal",
    "GoalNotFoundError",
    "GoalSnapshot",
    "GoalStore",
    "GoalValidationError",
    "SchemaVersionError",
    "process_key",
    "validate_goal",
]
