"""저장소가 돌려주는 값 객체. 모두 읽기 전용이라 호출부가 실수로 바꿔 저장소와 어긋나지 않는다."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SiteTarget:
    """목표에 연결하는 사이트 하나: 어느 브라우저(프로세스 이름)에서 본 어느 도메인인지.

    사용 시간이 브라우저별로 따로 집계되므로(같은 사이트라도 chrome과 edge는 따로 센다) 둘을 함께 가진다.
    """

    browser: str
    domain: str


@dataclass(frozen=True)
class Goal:
    """사용자가 설정한 목표 하나.

    weekdays는 목표를 적용하는 요일이다(파이썬 date.weekday()와 같다: 월=0 … 일=6). processes는 이
    목표에 연결된 프로세스 이름들(대소문자를 구분하지 않는 이름 순)이고, 한 프로세스는 하나의 목표에만
    연결된다. sites는 크롬·엣지 같은 브라우저의 "세부 페이지"(사이트)를 연결한 것으로, 브라우저 프로세스
    전체와 그 안의 사이트는 겹쳐 세지 않도록 함께 연결할 수 없다. created_at/updated_at은 UTC ISO 8601이다.
    """

    id: int
    name: str
    daily_target_minutes: int
    weekdays: frozenset[int]
    processes: tuple[str, ...]
    created_at: str
    updated_at: str
    sites: tuple[SiteTarget, ...] = ()


# 목표의 서버 동기화 선택: ask(아직 안 물음) / sync(서버와 동기화) / local_only(사용자가 올리지 않기로 함).
SYNC_STATES = ("ask", "sync", "local_only")


@dataclass(frozen=True)
class SyncLink:
    """목표 하나의 서버 연결 상태(docs/sync-design.md). 서버가 아는 것은 이름·목표 시간·요일뿐이고, 연결한
    프로세스·사이트는 여기에 없다.

    remote_id가 None이면 아직 서버에 없다. dirty는 연결된 목표를 로컬에서 고쳐 아직 서버에 못 보냈다는 뜻이다.
    """

    goal_id: int
    state: str
    remote_id: str | None
    remote_revision: int | None
    dirty: bool


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
    sites: tuple[SiteTarget, ...] = ()
