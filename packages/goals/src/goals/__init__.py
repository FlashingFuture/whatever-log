"""목표와 연결 프로세스의 모델·검증·저장.

이 패키지가 "목표가 무엇이고 무엇이 올바른 입력인지"의 유일한 원본이다. 화면은 입력을 받아 보여 줄
뿐이고, hub(/api/goals)와 나중의 전송 에이전트가 같은 코드를 그대로 쓴다. 목표 설정은 이 PC의
goals.db에만 저장되고, 그중 어떤 프로세스가 어느 목표에 속하는지(연결 프로세스)는 서버로 보내지 않는다.
보고서 요청 때 서버로 가는 것은 목표 이름, 설정 목표량, 달성 시간, 달성률뿐이다
(docs/data-handling.md, docs/goals-design.md).

- models: Goal, GoalSnapshot (읽기 전용 값 객체)
- validation: 입력 검증(엄격). 규칙의 상수도 여기 있다
- store: goals.db(SQLite) 저장소 — CRUD, 하루 스냅샷, 서버 연결 칸(docs/sync-design.md)
- progress: 목표별 수행 시간(연결 프로세스의 활성 시간 합)의 정의
- errors: 검증·조회 실패
"""

from goals.errors import FieldError, GoalNotFoundError, GoalValidationError, SchemaVersionError
from goals.models import SYNC_STATES, Goal, GoalSnapshot, SiteTarget, SyncLink
from goals.progress import GoalProgress, ProcessTime, ProgressSummary, SiteTime, TopTarget, compute_progress
from goals import sync_status
from goals.store import META_ACCOUNT_EMAIL, META_SYNC_ENABLED, GoalStore
from goals.validation import (
    MAX_GOALS,
    MAX_PROCESSES_PER_GOAL,
    MAX_SITES_PER_GOAL,
    is_valid_domain,
    is_valid_process_name,
    process_key,
    site_key,
    validate_goal,
)

__all__ = [
    "MAX_GOALS",
    "MAX_PROCESSES_PER_GOAL",
    "MAX_SITES_PER_GOAL",
    "META_ACCOUNT_EMAIL",
    "META_SYNC_ENABLED",
    "SYNC_STATES",
    "FieldError",
    "Goal",
    "GoalNotFoundError",
    "GoalProgress",
    "GoalSnapshot",
    "GoalStore",
    "GoalValidationError",
    "ProcessTime",
    "ProgressSummary",
    "SchemaVersionError",
    "SiteTarget",
    "SiteTime",
    "SyncLink",
    "TopTarget",
    "process_key",
    "sync_status",
    "compute_progress",
    "is_valid_domain",
    "is_valid_process_name",
    "site_key",
    "validate_goal",
]
