"""한 번의 동기화 주기(`sync_once`): 목표를 올리고·지우고·내려받고, 달성도를 보낸다.

규칙은 docs/sync-design.md의 "에이전트가 주기마다 하는 일"이다. 순서가 중요하다: **로컬 수정을 먼저 올리고 나서 내려받는다**
(이 PC에서 방금 한 수정이 서버의 낡은 값에 덮이지 않게). 네트워크 실패(ServerUnreachable)는 호출부(에이전트)가 다음 주기로
미루고, 항목 하나의 실패는 보고서에 적고 나머지를 계속한다. 이 함수는 기록·집계 DB를 읽기만 한다.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from cloud import GoalConflict, ProgressEntry, ServerError
from goals import META_ACCOUNT_EMAIL, META_SYNC_ENABLED, GoalStore, GoalValidationError

from goalsync.daily import day_entries, recent_days
from goalsync.plan import ServerPort, ensure_account
from goalsync.state import SyncState

NORMAL_DAYS = 8  # 오늘 + 지난 7일
FIRST_DAYS = 30  # 연결한 직후에는 한 달치를 보낸다
BATCH = 50  # 서버가 한 번에 받는 줄 수


@dataclass
class SyncReport:
    """한 주기의 결과. skipped가 있으면 아무것도 하지 않았다(이유: not_enabled·account_changed)."""

    skipped: str | None = None
    created: int = 0
    pushed: int = 0
    deleted: int = 0
    pulled: int = 0
    unlinked: int = 0
    progress_sent: int = 0
    problems: list[str] = field(default_factory=list)


def sync_once(
    store: GoalStore,
    state: SyncState,
    server,  # cloud.ServerApi 또는 같은 메서드를 가진 가짜
    recorder_db: Path,
    *,
    email: str | None,
    today: date,
    new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> SyncReport:
    """로그인된 사용자의 동기화를 한 번 한다. 동기화를 켜지 않았거나 계정이 바뀌었으면 아무것도 하지 않는다."""
    report = SyncReport()
    if ensure_account(store, email):
        state.forget_all()
        report.skipped = "account_changed"
        return report
    if store.get_meta(META_SYNC_ENABLED) != "1":
        report.skipped = "not_enabled"
        return report
    if email and store.get_meta(META_ACCOUNT_EMAIL) is None:
        store.set_meta(META_ACCOUNT_EMAIL, email)

    _delete_on_server(store, server, report)
    _upload_new_goals(store, server, report, new_id)
    _push_edits(store, server, report)
    _pull(store, state, server, report)
    _push_progress(store, state, server, recorder_db, today, report)
    return report


def _delete_on_server(store: GoalStore, server: ServerPort, report: SyncReport) -> None:
    """이 PC에서 지운 연결 목표를 서버에서도 지운다(이미 없어도 성공)."""
    for remote_id in store.pending_deletions():
        server.delete_goal(remote_id)
        store.clear_deletion(remote_id)
        report.deleted += 1


def _upload_new_goals(store: GoalStore, server: ServerPort, report: SyncReport, new_id: Callable[[], str]) -> None:
    """올리기로 정했지만 아직 서버에 없는 목표를 올린다."""
    for link in store.sync_links():
        if link.state != "sync" or link.remote_id is not None:
            continue
        goal = store.get(link.goal_id)
        if goal is None:
            continue
        try:
            created = server.put_goal(
                new_id(),
                name=goal.name,
                daily_target_minutes=goal.daily_target_minutes,
                weekdays=goal.weekdays,
                base_revision=0,
            )
        except GoalConflict as conflict:
            if conflict.code == "duplicate_name":
                # 서버에 같은 이름이 이미 있다(다른 기기에서 만든 목표). 조용히 합치지 않고 올리지 않는다.
                store.set_sync_state(link.goal_id, "local_only")
                report.problems.append(f"'{goal.name}': 서버에 같은 이름의 목표가 있어 올리지 않았습니다.")
            else:
                report.problems.append(f"'{goal.name}': {conflict.message}")
            continue
        store.link_remote(link.goal_id, created.id, created.revision)
        report.created += 1


def _push_edits(store: GoalStore, server: ServerPort, report: SyncReport) -> None:
    """이 PC에서 고친(dirty) 연결 목표를 서버에 보낸다. 다른 기기가 먼저 고쳤다면 서버의 최신 revision 위에 이 PC의 값을 다시 보낸다."""
    for link in store.sync_links():
        if not (link.dirty and link.remote_id and link.remote_revision is not None):
            continue
        goal = store.get(link.goal_id)
        if goal is None:
            continue
        revision = link.remote_revision
        for attempt in range(2):
            try:
                pushed = server.put_goal(
                    link.remote_id,
                    name=goal.name,
                    daily_target_minutes=goal.daily_target_minutes,
                    weekdays=goal.weekdays,
                    base_revision=revision,
                )
            except GoalConflict as conflict:
                if conflict.code == "goal_deleted":
                    store.unlink(link.goal_id)  # 다른 기기에서 지운 목표 — 이 PC에는 남기고 연결만 끊는다
                    report.unlinked += 1
                elif conflict.code == "conflict" and conflict.current is not None and attempt == 0:
                    revision = conflict.current.revision  # 이 PC의 값을 서버의 최신 위에 다시 보낸다
                    continue
                else:
                    report.problems.append(f"'{goal.name}': {conflict.message}")
                break
            except ServerError as error:
                if error.status == 404:
                    store.unlink(link.goal_id)
                    report.unlinked += 1
                else:
                    report.problems.append(f"'{goal.name}': {error.message}")
                break
            store.mark_pushed(link.goal_id, pushed.revision)
            report.pushed += 1
            break


def _pull(store: GoalStore, state: SyncState, server: ServerPort, report: SyncReport) -> None:
    """서버의 변경을 이 PC에 반영한다(서버에서 지워진 목표는 지우지 않고 연결만 끊는다)."""
    remote = {goal.id: goal for goal in server.list_goals()}
    for link in store.sync_links():
        if link.remote_id is None or link.dirty:
            continue
        theirs = remote.get(link.remote_id)
        if theirs is None or theirs.deleted:
            store.unlink(link.goal_id)
            state.forget(link.remote_id)
            report.unlinked += 1
        elif theirs.revision != link.remote_revision:
            try:
                store.apply_remote(
                    link.goal_id,
                    name=theirs.name or "",
                    daily_target_minutes=theirs.daily_target_minutes or 0,
                    weekdays=theirs.weekdays,
                    revision=theirs.revision,
                )
            except GoalValidationError as error:
                report.problems.append(error.errors[0].message if error.errors else "서버의 변경을 반영하지 못했습니다.")
                continue
            report.pulled += 1


def _push_progress(
    store: GoalStore,
    state: SyncState,
    server,
    recorder_db: Path,
    today: date,
    report: SyncReport,
) -> None:
    """연결된 목표의 최근 며칠 달성 분을 계산해, 마지막으로 보낸 값과 다른 줄만 서버에 보낸다."""
    links = {link.goal_id: link for link in store.sync_links() if link.remote_id and link.state == "sync"}
    if not links or not recorder_db.exists():
        return
    fresh = [goal_id for goal_id, link in links.items() if not state.has_pushed_any(link.remote_id or "")]
    window = recent_days(today, FIRST_DAYS if fresh else NORMAL_DAYS)

    entries = day_entries(store, recorder_db, window, only_goal_ids=set(links))
    pending: list[tuple[str, str, int, int]] = []
    for entry in entries:
        remote_id = links[entry.goal_id].remote_id
        assert remote_id is not None
        # 처음 연결한 목표는 긴 기간을, 그렇지 않은 목표는 최근 며칠만 본다(같은 창에서 오래된 날을 다시 보내지 않는다).
        if entry.goal_id not in fresh and entry.day < window[-NORMAL_DAYS].isoformat():
            continue
        if state.pushed(remote_id, entry.day) == (entry.minutes, entry.target_minutes):
            continue
        pending.append((remote_id, entry.day, entry.minutes, entry.target_minutes))

    for start in range(0, len(pending), BATCH):
        chunk = pending[start : start + BATCH]
        result = server.put_progress(
            state.device_id(), [ProgressEntry(remote_id, day, minutes, target) for remote_id, day, minutes, target in chunk]
        )
        ignored = set(result.ignored_goal_ids)
        for remote_id, day, minutes, target in chunk:
            if remote_id not in ignored:
                state.record_pushed(remote_id, day, minutes, target)
                report.progress_sent += 1
