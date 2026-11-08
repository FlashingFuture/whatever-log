from datetime import UTC, date, datetime, time, timedelta

from pathlib import Path

import pytest
from cloud import ServerUnreachable
from goals import META_ACCOUNT_EMAIL, META_SYNC_ENABLED
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from goalsync import sync_once

EMAIL = "a@example.com"
TODAY = date(2026, 11, 5)


def goal_fields(**overrides):
    fields = {"name": "공부", "daily_target_minutes": 120, "weekdays": [0, 1, 2, 3, 4], "processes": []}
    fields.update(overrides)
    return fields


def make_recorder_db(path: Path, ticks: dict[date, list[tuple[str, int]]]) -> Path:
    """로컬 날짜별로 (프로세스, 15초 틱 수)를 정오부터 이어 붙여 recorder.db를 만든다. 사이트는 `process:domain`으로 줄 수 있다."""
    conn = open_db(path)
    for day, runs in ticks.items():
        moment = datetime.combine(day, time(12, 0)).astimezone()
        for spec, count in runs:
            process, _, site = spec.partition(":")
            for _ in range(count + 1):  # 마지막 틱은 집계에서 빠지므로 하나 더 둔다
                save_tick(
                    conn,
                    TickSample(
                        sampled_at=moment.astimezone(UTC),
                        foreground_process=process,
                        windowed_processes=frozenset({process}),
                        seconds_since_last_input=0.0,
                        foreground_site=site or None,
                    ),
                )
                moment += timedelta(seconds=15)
    conn.close()
    return path


@pytest.fixture
def recorder_db(tmp_path):
    return make_recorder_db(tmp_path / "recorder.db", {})


def _enable(store, email=EMAIL):
    store.set_meta(META_SYNC_ENABLED, "1")
    store.set_meta(META_ACCOUNT_EMAIL, email)


def _run(store, state, server, recorder_db, *, email=EMAIL, today=TODAY, **options):
    return sync_once(store, state, server, recorder_db, email=email, today=today, **options)


def _linked(store, server, *, name="공부", remote_id="r-1", **fields):
    """서버와 연결된 목표 하나(이 PC와 서버 양쪽에 있다)."""
    goal = store.create(**goal_fields(name=name, **fields))
    remote = server.add(remote_id, name, minutes=goal.daily_target_minutes, weekdays=tuple(goal.weekdays))
    store.link_remote(goal.id, remote_id, remote.revision)
    return goal


def test_nothing_happens_until_the_user_has_confirmed(store, state, server, recorder_db) -> None:
    store.create(**goal_fields())

    report = _run(store, state, server, recorder_db)

    assert report.skipped == "not_enabled" and server.calls == []


def test_a_different_account_stops_the_cycle_and_cuts_the_old_links(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store, "old@example.com")
    state.record_pushed("r-1", "2026-11-05", 5, 120)

    report = _run(store, state, server, recorder_db, email="new@example.com")

    assert report.skipped == "account_changed" and server.calls == []
    assert store.sync_links()[0].remote_id is None and store.get(goal.id) is not None
    assert state.pushed("r-1", "2026-11-05") is None


def test_goals_chosen_for_sync_are_uploaded(store, state, server, recorder_db) -> None:
    goal = store.create(**goal_fields())
    store.set_sync_state(goal.id, "sync")
    _enable(store)

    report = _run(store, state, server, recorder_db, new_id=lambda: "r-new")

    assert report.created == 1
    assert store.sync_links()[0].remote_id == "r-new" and server.goals["r-new"].name == "공부"


def test_goals_the_user_kept_local_are_never_uploaded(store, state, server, recorder_db) -> None:
    store.create(**goal_fields(name="A"))
    declined = store.create(**goal_fields(name="B"))
    store.set_sync_state(declined.id, "local_only")
    _enable(store)

    _run(store, state, server, recorder_db)

    assert server.goals == {}


def test_a_name_taken_on_the_server_is_reported_and_not_merged_silently(store, state, server, recorder_db) -> None:
    goal = store.create(**goal_fields())
    store.set_sync_state(goal.id, "sync")
    server.add("r-other", "공부")
    _enable(store)

    report = _run(store, state, server, recorder_db)

    assert report.created == 0 and "같은 이름" in report.problems[0]
    assert store.sync_links()[0].state == "local_only"  # 같은 문제를 매 주기 되풀이하지 않는다


def test_a_local_edit_is_pushed_with_the_known_revision(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store)
    store.update(goal.id, **goal_fields(daily_target_minutes=90))

    report = _run(store, state, server, recorder_db)

    assert report.pushed == 1
    assert server.goals["r-1"].daily_target_minutes == 90 and server.goals["r-1"].revision == 2
    link = store.sync_links()[0]
    assert (link.dirty, link.remote_revision) == (False, 2)


def test_a_clean_goal_is_not_pushed_again(store, state, server, recorder_db) -> None:
    _linked(store, server)
    _enable(store)

    _run(store, state, server, recorder_db)

    assert not any(call.startswith("put_goal") for call in server.calls)


def test_when_another_device_edited_first_the_local_value_is_resent_on_top(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store)
    server.edit("r-1", daily_target_minutes=30)  # 다른 기기가 먼저 고쳤다(revision 2)
    store.update(goal.id, **goal_fields(daily_target_minutes=90))

    report = _run(store, state, server, recorder_db)

    assert report.pushed == 1 and report.problems == []
    assert server.goals["r-1"].daily_target_minutes == 90 and server.goals["r-1"].revision == 3
    assert store.get(goal.id).daily_target_minutes == 90  # 이 PC의 값이 이겼다
    assert store.sync_links()[0].remote_revision == 3


def test_an_edit_to_a_goal_deleted_elsewhere_unlinks_it_and_keeps_it_here(store, state, server, recorder_db) -> None:
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    server.remove("r-1")
    store.update(goal.id, **goal_fields(daily_target_minutes=90, processes=["Code.exe"]))

    report = _run(store, state, server, recorder_db)

    assert report.unlinked == 1
    assert store.sync_links()[0].state == "local_only" and store.get(goal.id).processes == ("Code.exe",)


def test_a_rename_that_collides_on_the_server_stays_pending_and_is_reported(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    server.add("r-2", "운동")
    _enable(store)
    store.update(goal.id, **goal_fields(name="운동"))

    report = _run(store, state, server, recorder_db)

    assert report.pushed == 0 and "같은 이름" in report.problems[0]
    assert store.sync_links()[0].dirty is True  # 사용자가 이름을 바꾸면 다음 주기에 올라간다


def test_goals_deleted_here_are_deleted_on_the_server_and_forgotten(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store)
    store.delete(goal.id)

    report = _run(store, state, server, recorder_db)

    assert report.deleted == 1 and server.goals["r-1"].deleted is True
    assert store.pending_deletions() == []


def test_a_deletion_that_could_not_be_sent_is_kept_for_the_next_cycle(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store)
    store.delete(goal.id)
    server.unreachable = True

    with pytest.raises(ServerUnreachable):
        _run(store, state, server, recorder_db)
    assert store.pending_deletions() == ["r-1"]

    server.unreachable = False
    _run(store, state, server, recorder_db)
    assert store.pending_deletions() == [] and server.goals["r-1"].deleted is True


def test_a_server_change_is_pulled_into_a_clean_goal_and_process_links_stay(store, state, server, recorder_db) -> None:
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    server.edit("r-1", name="새 이름", daily_target_minutes=45, weekdays=frozenset({5, 6}))

    report = _run(store, state, server, recorder_db)

    updated = store.get(goal.id)
    assert report.pulled == 1
    assert (updated.name, updated.daily_target_minutes, updated.weekdays, updated.processes) == (
        "새 이름",
        45,
        frozenset({5, 6}),
        ("Code.exe",),
    )
    assert store.sync_links()[0].remote_revision == 2


def test_an_unchanged_server_goal_is_left_alone(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store)
    before = store.get(goal.id)

    report = _run(store, state, server, recorder_db)

    assert report.pulled == 0 and store.get(goal.id) == before


def test_a_server_deletion_unlinks_without_deleting_the_goal_here(store, state, server, recorder_db) -> None:
    goal = _linked(store, server, processes=["Code.exe"])
    _enable(store)
    server.remove("r-1")

    report = _run(store, state, server, recorder_db)

    assert report.unlinked == 1
    assert store.get(goal.id).processes == ("Code.exe",)
    assert store.sync_links()[0] == store.sync_links()[0].__class__(goal.id, "local_only", None, None, False)


def test_a_goal_the_server_no_longer_knows_at_all_is_unlinked_too(store, state, server, recorder_db) -> None:
    _linked(store, server)
    _enable(store)
    server.forget("r-1")  # 삭제 표시도 정리됐다(30일 뒤)

    report = _run(store, state, server, recorder_db)

    assert report.unlinked == 1 and store.sync_links()[0].state == "local_only"


def test_a_pull_that_would_collide_with_a_local_name_is_reported_not_applied(store, state, server, recorder_db) -> None:
    goal = _linked(store, server, name="공부")
    store.create(**goal_fields(name="운동"))
    _enable(store)
    server.edit("r-1", name="운동")

    report = _run(store, state, server, recorder_db)

    assert report.pulled == 0 and report.problems and store.get(goal.id).name == "공부"


def test_server_only_goals_are_not_brought_over_automatically(store, state, server, recorder_db) -> None:
    server.add("r-9", "다른 기기의 목표")
    _enable(store)

    _run(store, state, server, recorder_db)

    assert store.list_goals() == []


def test_the_first_cycle_after_a_network_failure_resumes_without_losing_edits(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store)
    store.update(goal.id, **goal_fields(daily_target_minutes=90))
    server.unreachable = True
    with pytest.raises(ServerUnreachable):
        _run(store, state, server, recorder_db)
    assert store.sync_links()[0].dirty is True

    server.unreachable = False
    _run(store, state, server, recorder_db)

    assert server.goals["r-1"].daily_target_minutes == 90 and store.sync_links()[0].dirty is False


# --- 달성도 ---


def test_progress_is_sent_for_linked_goals_only(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {TODAY: [("Code.exe", 40), ("chrome.exe", 40)]})  # 각 10분
    linked = _linked(store, server, processes=["Code.exe"])
    store.create(**goal_fields(name="로컬", processes=["chrome.exe"]))
    _enable(store)

    report = _run(store, state, server, db)

    assert report.progress_sent >= 1
    device = state.device_id()
    assert server.progress[("r-1", device, TODAY.isoformat())] == (10, 120)
    assert {goal_id for goal_id, _, _ in server.progress} == {"r-1"}
    assert linked.id  # 로컬 전용 목표의 시간은 어디에도 가지 않았다


def test_the_servers_progress_rows_never_contain_process_names(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {TODAY: [("Secret.exe", 40)]})
    _linked(store, server, processes=["Secret.exe"])
    _enable(store)

    _run(store, state, server, db)

    assert "Secret.exe" not in repr(server.progress) and "Secret.exe" not in repr(server.calls)


def test_unchanged_progress_is_not_sent_twice(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {TODAY: [("Code.exe", 40)]})
    _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, db)
    server.calls.clear()

    report = _run(store, state, server, db)

    assert report.progress_sent == 0 and "put_progress" not in server.calls


def test_changed_progress_is_sent_again(tmp_path, store, state, server) -> None:
    path = tmp_path / "r.db"
    make_recorder_db(path, {TODAY: [("Code.exe", 40)]})
    _linked(store, server, processes=["Code.exe"])
    _enable(store)
    _run(store, state, server, path)

    make_recorder_db(tmp_path / "more.db", {TODAY: [("Code.exe", 80)]})
    report = _run(store, state, server, tmp_path / "more.db")

    assert report.progress_sent == 1
    assert server.progress[("r-1", state.device_id(), TODAY.isoformat())] == (20, 120)


def test_a_newly_linked_goal_gets_a_month_and_later_cycles_only_the_last_week(tmp_path, store, state, server) -> None:
    day_old = date(2026, 10, 20)  # 오늘(11-05)로부터 16일 전
    db = make_recorder_db(tmp_path / "r.db", {day_old: [("Code.exe", 40)], TODAY: [("Code.exe", 40)]})
    _linked(store, server, processes=["Code.exe"])
    _enable(store)

    _run(store, state, server, db)
    assert ("r-1", state.device_id(), day_old.isoformat()) in server.progress  # 처음에는 30일을 본다

    state.forget("r-1")
    state.record_pushed("r-1", "2026-11-05", 0, 120)  # 이미 한 번 보낸 목표가 됐다
    server.progress.clear()
    _run(store, state, server, db)
    assert ("r-1", state.device_id(), day_old.isoformat()) not in server.progress  # 그 뒤로는 최근 8일만


def test_site_time_counts_toward_a_goal_linked_to_that_site(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {TODAY: [("chrome.exe:youtube.com", 40)]})
    goal = store.create(**goal_fields(sites=[{"browser": "chrome.exe", "domain": "youtube.com"}]))
    server.add("r-1", "공부")
    store.link_remote(goal.id, "r-1", 1)
    _enable(store)

    _run(store, state, server, db)

    assert server.progress[("r-1", state.device_id(), TODAY.isoformat())][0] == 10


def test_progress_the_server_ignores_is_not_recorded_as_sent(tmp_path, store, state, server) -> None:
    db = make_recorder_db(tmp_path / "r.db", {TODAY: [("Code.exe", 40)]})
    _linked(store, server, processes=["Code.exe"])
    _enable(store)
    server.remove("r-1")  # 보내는 순간 서버에서는 이미 지워진 목표다

    report = _run(store, state, server, db)

    assert state.pushed("r-1", TODAY.isoformat()) is None and report.progress_sent == 0


def test_a_missing_recorder_db_is_not_an_error(tmp_path, store, state, server) -> None:
    _linked(store, server)
    _enable(store)

    report = _run(store, state, server, tmp_path / "nope.db")

    assert report.progress_sent == 0


def test_more_than_fifty_rows_are_sent_in_batches(tmp_path, store, state, server) -> None:
    days = {TODAY - timedelta(days=n): [("Code.exe", 8)] for n in range(0, 30)}
    db = make_recorder_db(tmp_path / "r.db", days)
    for index in range(3):
        goal = store.create(**goal_fields(name=f"G{index}", processes=[f"P{index}.exe"] if index else ["Code.exe"]))
        server.add(f"r-{index}", f"G{index}")
        store.link_remote(goal.id, f"r-{index}", 1)
    _enable(store)

    _run(store, state, server, db)

    assert server.calls.count("put_progress") >= 2  # 30일 × 요일에 맞는 줄이 50줄을 넘으면 나눠 보낸다


def test_the_device_id_is_stable_and_not_a_hardware_value(state) -> None:
    first = state.device_id()

    assert state.device_id() == first
    import re

    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", first)


def test_a_local_edit_that_could_not_be_pushed_is_not_overwritten_by_a_newer_server_value(
    store, state, server, recorder_db
) -> None:
    goal = _linked(store, server, name="공부")
    server.add("r-2", "운동")
    _enable(store)
    server.edit("r-1", daily_target_minutes=30)  # 서버의 revision이 앞서 있다
    store.update(goal.id, **goal_fields(name="운동", daily_target_minutes=90))  # 서버의 다른 목표와 이름이 겹쳐 올라가지 못한다

    report = _run(store, state, server, recorder_db)

    assert report.pushed == 0 and report.pulled == 0 and report.problems
    kept = store.get(goal.id)
    assert (kept.name, kept.daily_target_minutes) == ("운동", 90)  # 사용자의 수정이 사라지지 않았다
    assert store.sync_links()[0].dirty is True


# --- 주기 도중 계정이 정리되는 경우 ---


class _ResetsMidCycle:
    """서버 호출이 끝나는 순간(응답을 받은 직후) 다른 프로세스(화면)가 계정을 정리한 상황을 흉내 낸다."""

    def __init__(self, server, store, on: str) -> None:
        self._server, self._store, self._on = server, store, on

    def __getattr__(self, name):
        attribute = getattr(self._server, name)
        if name != self._on:
            return attribute

        def call(*args, **kwargs):
            result = attribute(*args, **kwargs)
            self._store.reset_sync()  # 서버 응답은 받았지만 저장하기 전에 계정이 정리되었다
            return result

        return call


def test_an_upload_answered_just_before_the_account_was_cleared_is_not_linked_afterwards(store, state, server, recorder_db) -> None:
    goal = store.create(**goal_fields())
    store.set_sync_state(goal.id, "sync")
    _enable(store)

    report = _run(store, state, _ResetsMidCycle(server, store, "put_goal"), recorder_db, new_id=lambda: "r-new")

    assert report.skipped == "account_changed"
    link = store.sync_links()[0]
    assert (link.remote_id, link.state) == (None, "ask")  # 이전 계정의 연결이 정리된 DB에 되살아나지 않았다
    assert store.get_meta(META_SYNC_ENABLED) is None


def test_a_pull_that_finishes_after_the_account_was_cleared_changes_nothing(store, state, server, recorder_db) -> None:
    goal = _linked(store, server)
    _enable(store)
    server.edit("r-1", name="서버 새 이름")

    report = _run(store, state, _ResetsMidCycle(server, store, "list_goals"), recorder_db)

    # 정리된 뒤에는 이어서 쓸 연결이 없어 아무것도 쓰지 않는다. 낡은 세대로 상태를 적으려는 시도는 호출부(에이전트)가 거절당한다.
    assert store.get(goal.id).name == "공부" and store.sync_links()[0].remote_id is None
    assert report.generation != store.generation()


def test_the_cycle_reports_its_generation_so_a_late_status_can_be_refused(store, state, server, recorder_db) -> None:
    _enable(store)

    first = _run(store, state, server, recorder_db)
    store.reset_sync()

    assert first.generation is not None and first.generation != store.generation()


def test_a_cycle_cut_off_by_an_account_reset_still_reports_the_generation_it_started_with(store, state, server, recorder_db) -> None:
    goal = store.create(**goal_fields())
    store.set_sync_state(goal.id, "sync")
    _enable(store)
    started = store.generation()

    report = _run(store, state, _ResetsMidCycle(server, store, "put_goal"), recorder_db, new_id=lambda: "r-new")

    assert report.skipped == "account_changed"
    assert report.generation == started != store.generation()  # 호출부가 이 세대로 상태 기록을 거절시킬 수 있다
