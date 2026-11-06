"""로그인 직후의 확인: 이 PC의 목표와 서버의 목표를 견줘 "무엇을 어떻게 할지" 계획을 만들고, 사용자의 선택을 적용한다.

계획의 항목은 세 종류다(docs/sync-design.md):
- upload: 이 PC에만 있는 목표 → 서버에 새로 올린다.
- merge: 이 PC와 같은 이름의 서버 목표가 있다 → 올리지 않고 그 서버 목표와 연결한다(목표 시간·요일은 서버 값).
- download: 서버에만 있는 목표 → 이 PC에 연결 없는 목표로 가져온다.

서버로 가는 것은 이름·목표 시간·요일뿐이다. 프로세스·사이트 연결은 어느 항목에서도 올라가지 않는다.
"""

import uuid
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from cloud import GoalConflict, RemoteGoal, ServerError
from goals import META_ACCOUNT_EMAIL, META_SYNC_ENABLED, Goal, GoalStore, GoalValidationError, SyncLink
from goals.validation import name_key

KIND_UPLOAD = "upload"
KIND_MERGE = "merge"
KIND_DOWNLOAD = "download"


class ServerPort(Protocol):
    """동기화가 서버에 바라는 것. 진짜 구현은 `cloud.ServerApi`이고, 테스트는 메모리 가짜를 넣는다."""

    def list_goals(self) -> list[RemoteGoal]:
        """내 목표 전부(삭제 표시 포함)."""
        ...

    def put_goal(
        self, goal_id: str, *, name: str, daily_target_minutes: int, weekdays: Collection[int], base_revision: int
    ) -> RemoteGoal:
        """목표를 만들거나(base_revision 0) 고친다."""
        ...

    def delete_goal(self, goal_id: str) -> bool:
        """목표를 삭제한다(이미 없으면 False)."""
        ...


@dataclass(frozen=True)
class PlanItem:
    """확인 창의 한 줄. key는 화면과 주고받는 안정된 이름이고, 올라가는 값(name·target·weekdays)을 그대로 보여 준다.

    merge일 때만 local_*에 이 PC의 값이 있다(서버 값과 다르면 화면이 둘을 함께 보여 준다).
    declined는 사용자가 전에 "올리지 않기"를 골랐던 목표다(기본 선택을 끈다).
    """

    key: str
    kind: str
    name: str
    daily_target_minutes: int
    weekdays: tuple[int, ...]
    local_id: int | None = None
    remote_id: str | None = None
    local_daily_target_minutes: int | None = None
    local_weekdays: tuple[int, ...] | None = None
    declined: bool = False
    # 계획을 만들 때 본 서버 revision(merge·download). 그 뒤 서버가 바뀌었다면 다음 주기의 내려받기가 맞춘다.
    remote_revision: int | None = None


@dataclass(frozen=True)
class Plan:
    """확인 창이 보여 줄 전체. enabled는 이 계정에서 이미 한 번 확인을 마쳤는지(처음이면 로그인 직후 자동으로 창을 연다)."""

    email: str | None
    enabled: bool
    items: tuple[PlanItem, ...]


@dataclass(frozen=True)
class ApplyResult:
    """적용 결과: 항목별 개수와 실패한 항목(key, 사용자에게 보여 줄 사유)."""

    uploaded: int = 0
    merged: int = 0
    downloaded: int = 0
    kept_local: int = 0
    errors: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def local_key(goal_id: int) -> str:
    """이 PC 목표의 항목 이름."""
    return f"local:{goal_id}"


def remote_key(remote_id: str) -> str:
    """서버 목표의 항목 이름."""
    return f"remote:{remote_id}"


def ensure_account(store: GoalStore, email: str | None) -> bool:
    """저장해 둔 계정(이메일)과 지금 로그인한 계정이 다르면 이전 계정에 대한 연결을 모두 끊는다.

    다른 계정에 이전 계정의 목표가 올라가거나 지워지지 않게 하는 안전장치다. 끊었으면 True.
    이메일을 알 수 없으면(None) 비교할 수 없으므로 아무것도 하지 않는다.
    """
    stored = store.get_meta(META_ACCOUNT_EMAIL)
    if email is None or stored is None or stored == email:
        return False
    store.reset_sync()
    return True


def build_plan(store: GoalStore, remote_goals: list[RemoteGoal], email: str | None) -> Plan:
    """로컬 목표와 서버 목표를 견줘 계획을 만든다. 계정이 바뀌었으면 먼저 이전 연결을 끊는다."""
    ensure_account(store, email)
    goals = store.list_goals()
    links: Mapping[int, SyncLink] = {link.goal_id: link for link in store.sync_links()}
    linked_remote_ids = {link.remote_id for link in links.values() if link.remote_id}

    # 서버에 있는 목표 중 아직 이 PC의 어느 목표와도 연결되지 않은 것(살아 있는 것만)
    free_remote: dict[str, RemoteGoal] = {
        goal.id: goal for goal in remote_goals if not goal.deleted and goal.id not in linked_remote_ids
    }
    by_name = {name_key(goal.name or ""): goal for goal in free_remote.values()}

    items: list[PlanItem] = []
    for goal in goals:
        link = links[goal.id]
        # 이미 서버와 연결됐거나, 올리기로 정해 두었고 곧 올라갈 목표는 묻지 않는다.
        if link.remote_id is not None or link.state == "sync":
            continue
        match = by_name.pop(name_key(goal.name), None)
        if match is not None:
            free_remote.pop(match.id, None)
            items.append(
                PlanItem(
                    key=local_key(goal.id),
                    kind=KIND_MERGE,
                    name=match.name or goal.name,
                    daily_target_minutes=match.daily_target_minutes or goal.daily_target_minutes,
                    weekdays=tuple(sorted(match.weekdays)),
                    local_id=goal.id,
                    remote_id=match.id,
                    local_daily_target_minutes=goal.daily_target_minutes,
                    local_weekdays=tuple(sorted(goal.weekdays)),
                    declined=link.state == "local_only",
                    remote_revision=match.revision,
                )
            )
        else:
            items.append(
                PlanItem(
                    key=local_key(goal.id),
                    kind=KIND_UPLOAD,
                    name=goal.name,
                    daily_target_minutes=goal.daily_target_minutes,
                    weekdays=tuple(sorted(goal.weekdays)),
                    local_id=goal.id,
                    declined=link.state == "local_only",
                )
            )
    for remote in free_remote.values():
        items.append(
            PlanItem(
                key=remote_key(remote.id),
                kind=KIND_DOWNLOAD,
                name=remote.name or "",
                daily_target_minutes=remote.daily_target_minutes or 0,
                weekdays=tuple(sorted(remote.weekdays)),
                remote_id=remote.id,
                remote_revision=remote.revision,
            )
        )
    return Plan(email=email, enabled=store.get_meta(META_SYNC_ENABLED) == "1", items=tuple(items))


def _explain(error: Exception) -> str:
    """사용자에게 보여 줄 실패 사유."""
    if isinstance(error, GoalConflict):
        return {
            "duplicate_name": "서버에 같은 이름의 목표가 이미 있습니다.",
            "too_many_goals": "서버에는 목표를 20개까지 둘 수 있습니다.",
        }.get(error.code, error.message)
    if isinstance(error, ServerError):
        return error.message
    if isinstance(error, GoalValidationError) and error.errors:
        return error.errors[0].message
    return "처리하지 못했습니다."


def apply_choices(
    store: GoalStore,
    server: ServerPort,
    plan: Plan,
    accepted: Collection[str],
    *,
    new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> ApplyResult:
    """사용자의 선택(accepted: 체크한 항목의 key)을 적용한다.

    체크한 항목은 올리기·합치기·가져오기를 하고, 체크하지 않은 이 PC 목표는 `local_only`(올리지 않음)로 둔다.
    계획에 없는 key는 무시한다. 동기화를 켜고(이후 새 목표는 자동으로 서버와 맞춘다) 계정을 기록한 뒤 처리하며,
    한 항목이 실패해도 나머지는 계속한다(실패한 올리기는 에이전트가 다음 주기에 다시 시도한다).
    네트워크가 끊기면 ServerUnreachable이 그대로 올라간다.
    """
    store.set_meta(META_SYNC_ENABLED, "1")
    if plan.email:
        store.set_meta(META_ACCOUNT_EMAIL, plan.email)

    uploaded = merged = downloaded = kept_local = 0
    errors: list[tuple[str, str]] = []
    chosen = set(accepted)
    for item in plan.items:
        if item.kind in (KIND_UPLOAD, KIND_MERGE):
            assert item.local_id is not None
            if item.key not in chosen:
                store.set_sync_state(item.local_id, "local_only")
                kept_local += 1
                continue
            try:
                if item.kind == KIND_MERGE:
                    _merge(store, item)
                    merged += 1
                else:
                    _upload(store, server, item, new_id())
                    uploaded += 1
            except (ServerError, GoalValidationError) as error:
                errors.append((item.key, _explain(error)))
                if isinstance(error, GoalConflict) and error.code == "duplicate_name":
                    store.set_sync_state(item.local_id, "local_only")
        elif item.key in chosen:
            assert item.remote_id is not None
            try:
                store.create_from_remote(
                    remote_id=item.remote_id,
                    name=item.name,
                    daily_target_minutes=item.daily_target_minutes,
                    weekdays=item.weekdays,
                    revision=item.remote_revision or 0,
                )
                downloaded += 1
            except (ServerError, GoalValidationError) as error:
                errors.append((item.key, _explain(error)))
    return ApplyResult(uploaded, merged, downloaded, kept_local, tuple(errors))


def _upload(store: GoalStore, server: ServerPort, item: PlanItem, remote_id: str) -> None:
    """이 PC의 목표를 서버에 새로 올리고 연결한다."""
    assert item.local_id is not None
    store.set_sync_state(item.local_id, "sync")
    goal: Goal | None = store.get(item.local_id)
    if goal is None:
        return
    created = server.put_goal(
        remote_id,
        name=goal.name,
        daily_target_minutes=goal.daily_target_minutes,
        weekdays=goal.weekdays,
        base_revision=0,
    )
    store.link_remote(item.local_id, created.id, created.revision)


def _merge(store: GoalStore, item: PlanItem) -> None:
    """서버의 같은 이름 목표와 연결한다. 목표 시간·요일은 서버 값으로 맞추고 프로세스 연결은 그대로 둔다."""
    assert item.local_id is not None and item.remote_id is not None
    revision = item.remote_revision or 0
    store.apply_remote(
        item.local_id,
        name=item.name,
        daily_target_minutes=item.daily_target_minutes,
        weekdays=item.weekdays,
        revision=revision,
    )
    store.link_remote(item.local_id, item.remote_id, revision)
