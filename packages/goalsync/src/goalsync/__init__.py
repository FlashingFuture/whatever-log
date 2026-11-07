"""로컬 목표(goals.db)와 서버의 목표·달성도를 맞춘다(docs/sync-design.md).

- plan: 로그인 직후 "무엇을 서버에 올리고 합치고 가져올지" 계획을 만들고, 사용자의 선택을 적용한다
- runner: 주기마다 목표를 올리고·지우고·내려받고 달성도를 보내는 `sync_once`
- daily: recorder.db에서 날짜별 달성 분을 계산(수행 시간의 정의는 goals.compute_progress)
- state: 에이전트 자신의 상태(기기 ID, 마지막으로 보낸 값)

이 패키지는 서버를 부르므로 `cloud`에 의존한다. 따라서 recorder·집계·목표 같은 로컬 기능은 이 패키지를 쓰지 않는다
(packages/cloud/tests/test_isolation.py).
"""

from goalsync.plan import (
    KIND_DOWNLOAD,
    KIND_MERGE,
    KIND_UPLOAD,
    ApplyResult,
    Plan,
    PlanItem,
    ServerPort,
    apply_choices,
    build_plan,
    ensure_account,
)
from goalsync.runner import SyncReport, sync_once
from goalsync.state import SyncState, peek_device_id

__all__ = [
    "KIND_DOWNLOAD",
    "KIND_MERGE",
    "KIND_UPLOAD",
    "ApplyResult",
    "Plan",
    "PlanItem",
    "ServerPort",
    "SyncReport",
    "SyncState",
    "apply_choices",
    "build_plan",
    "ensure_account",
    "peek_device_id",
    "sync_once",
]
