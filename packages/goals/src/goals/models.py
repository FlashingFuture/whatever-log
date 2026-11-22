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
    # 목표의 기간(로컬 날짜, 양끝 포함). 둘 다 None이면 기간이 없는(무기한) 목표다 — 정하면 항상 둘 다 있다(검증이 보장한다).
    start_date: date | None = None
    end_date: date | None = None

    def covers(self, day: date) -> bool:
        """그날이 목표의 기간 안인가. 기간이 없으면 항상 True."""
        if self.start_date is None or self.end_date is None:
            return True
        return self.start_date <= day <= self.end_date

    def applies_on(self, day: date) -> bool:
        """그날 이 목표가 적용되는가: 요일이 맞고 기간 안이다. 목표량(분모)과 수행 시간(분자) 모두 이 날들만 센다."""
        return day.weekday() in self.weekdays and self.covers(day)

    def ended_before(self, day: date) -> bool:
        """기간이 정해져 있고 그날 이전에 끝났는가(종료됨). 기간이 없으면 끝나지 않는다."""
        return self.end_date is not None and self.end_date < day


# 목표의 서버 동기화 선택: ask(아직 안 물음) / sync(서버와 동기화) / local_only(사용자가 올리지 않기로 함).
SYNC_STATES = ("ask", "sync", "local_only")


@dataclass(frozen=True)
class SyncLink:
    """목표 하나의 서버 연결 상태(docs/sync-client.md). 서버가 아는 것은 이름·목표 시간·요일뿐이고, 연결한
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
