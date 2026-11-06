import pytest
from cloud import ServerUnreachable
from goals import META_ACCOUNT_EMAIL, META_SYNC_ENABLED

from goalsync import KIND_DOWNLOAD, KIND_MERGE, KIND_UPLOAD, apply_choices, build_plan
from goalsync.plan import ensure_account, local_key, remote_key

EMAIL = "a@example.com"


def goal_fields(**overrides):
    fields = {"name": "공부", "daily_target_minutes": 120, "weekdays": [0, 1, 2, 3, 4], "processes": []}
    fields.update(overrides)
    return fields


def _plan(store, server, email=EMAIL):
    return build_plan(store, server.list_goals(), email)


def _by_kind(plan):
    return {item.key: item for item in plan.items}


def test_a_local_only_goal_is_an_upload_with_the_values_that_would_go_out(store, server) -> None:
    goal = store.create(**goal_fields(processes=["Code.exe"]))

    plan = _plan(store, server)

    (item,) = plan.items
    assert (item.kind, item.key, item.name, item.daily_target_minutes, item.weekdays) == (
        KIND_UPLOAD,
        local_key(goal.id),
        "공부",
        120,
        (0, 1, 2, 3, 4),
    )
    assert plan.enabled is False and plan.email == EMAIL


def test_the_plan_never_mentions_processes_or_sites(store, server) -> None:
    store.create(**goal_fields(processes=["Code.exe"]))

    (item,) = _plan(store, server).items

    assert "Code.exe" not in repr(item)


def test_a_goal_with_the_same_name_on_the_server_is_a_merge_that_shows_both_values(store, server) -> None:
    goal = store.create(**goal_fields(name="Study", daily_target_minutes=60, weekdays=[0]))
    server.add("r-1", "STUDY", minutes=90, weekdays=(1, 2), revision=4)

    (item,) = _plan(store, server).items

    assert item.kind == KIND_MERGE and item.local_id == goal.id and item.remote_id == "r-1"
    assert (item.daily_target_minutes, item.weekdays) == (90, (1, 2))  # 서버 값(합치면 이 값이 된다)
    assert (item.local_daily_target_minutes, item.local_weekdays) == (60, (0,))
    assert item.remote_revision == 4


def test_server_only_goals_are_downloads_and_deleted_ones_are_not_listed(store, server) -> None:
    server.add("r-1", "독서")
    server.add("r-2", "지운 것")
    server.remove("r-2")

    (item,) = _plan(store, server).items

    assert (item.kind, item.key, item.name) == (KIND_DOWNLOAD, remote_key("r-1"), "독서")


def test_goals_already_linked_or_already_chosen_for_sync_are_not_asked_again(store, server) -> None:
    linked = store.create(**goal_fields(name="A"))
    chosen = store.create(**goal_fields(name="B"))
    store.link_remote(linked.id, "r-1", 1)
    server.add("r-1", "A")
    store.set_sync_state(chosen.id, "sync")

    assert _plan(store, server).items == ()


def test_a_goal_the_user_declined_before_is_listed_but_marked_declined(store, server) -> None:
    goal = store.create(**goal_fields())
    store.set_sync_state(goal.id, "local_only")

    (item,) = _plan(store, server).items

    assert item.declined is True


def test_the_plan_reports_whether_this_account_already_confirmed(store, server) -> None:
    store.set_meta(META_SYNC_ENABLED, "1")

    assert _plan(store, server).enabled is True


def test_a_different_account_cuts_every_old_link_before_planning(store, server) -> None:
    goal = store.create(**goal_fields(processes=["Code.exe"]))
    store.link_remote(goal.id, "r-old", 3)
    store.set_meta(META_ACCOUNT_EMAIL, "old@example.com")
    store.set_meta(META_SYNC_ENABLED, "1")

    plan = _plan(store, server, "new@example.com")

    (item,) = plan.items
    assert item.kind == KIND_UPLOAD and plan.enabled is False  # 새 계정에서는 다시 묻는다
    assert store.sync_links()[0].remote_id is None
    assert store.get(goal.id).processes == ("Code.exe",)


def test_ensure_account_does_nothing_without_a_stored_or_known_email(store) -> None:
    goal = store.create(**goal_fields())
    store.link_remote(goal.id, "r-1", 1)

    assert ensure_account(store, "a@example.com") is False  # 저장된 이메일이 없다
    store.set_meta(META_ACCOUNT_EMAIL, "a@example.com")
    assert ensure_account(store, None) is False  # 지금 이메일을 모른다
    assert ensure_account(store, "a@example.com") is False
    assert store.sync_links()[0].remote_id == "r-1"


# --- 적용 ---


def test_accepting_an_upload_creates_the_server_goal_and_links_it(store, server) -> None:
    goal = store.create(**goal_fields(processes=["Code.exe"]))
    plan = _plan(store, server)

    result = apply_choices(store, server, plan, [local_key(goal.id)], new_id=lambda: "r-new")

    link = store.sync_links()[0]
    assert (result.uploaded, result.errors) == (1, ())
    assert (link.state, link.remote_id, link.remote_revision, link.dirty) == ("sync", "r-new", 1, False)
    assert server.goals["r-new"].name == "공부" and server.goals["r-new"].weekdays == frozenset({0, 1, 2, 3, 4})
    assert store.get_meta(META_SYNC_ENABLED) == "1" and store.get_meta(META_ACCOUNT_EMAIL) == EMAIL


def test_nothing_about_the_process_links_reaches_the_server(store, server) -> None:
    goal = store.create(**goal_fields(processes=["Code.exe"]))

    apply_choices(store, server, _plan(store, server), [local_key(goal.id)], new_id=lambda: "r-new")

    assert "Code.exe" not in repr(server.goals) and "Code.exe" not in repr(server.calls)


def test_declining_keeps_the_goal_local_and_uploads_nothing(store, server) -> None:
    goal = store.create(**goal_fields())

    result = apply_choices(store, server, _plan(store, server), [])

    assert result.kept_local == 1 and result.uploaded == 0
    assert store.sync_links()[0].state == "local_only"
    assert server.goals == {} and "put_goal:0" not in server.calls
    assert store.get_meta(META_SYNC_ENABLED) == "1"  # 확인은 마쳤다 — 이후 새 목표는 자동으로 맞춘다
    assert goal.id == store.list_goals()[0].id


def test_merging_adopts_the_server_values_and_keeps_the_local_process_links(store, server) -> None:
    goal = store.create(**goal_fields(name="Study", daily_target_minutes=60, weekdays=[0], processes=["Code.exe"]))
    server.add("r-1", "study", minutes=90, weekdays=(1, 2), revision=4)

    result = apply_choices(store, server, _plan(store, server), [local_key(goal.id)])

    merged = store.get(goal.id)
    assert result.merged == 1
    assert (merged.name, merged.daily_target_minutes, merged.weekdays, merged.processes) == (
        "study",
        90,
        frozenset({1, 2}),
        ("Code.exe",),
    )
    link = store.sync_links()[0]
    assert (link.remote_id, link.remote_revision, link.dirty) == ("r-1", 4, False)
    assert "put_goal:0" not in server.calls  # 새로 올리지 않는다
    assert len(server.goals) == 1


def test_declining_a_merge_keeps_both_goals_separate(store, server) -> None:
    goal = store.create(**goal_fields(name="Study"))
    server.add("r-1", "study")

    apply_choices(store, server, _plan(store, server), [])

    assert store.sync_links()[0].state == "local_only" and store.sync_links()[0].remote_id is None
    assert store.get(goal.id).name == "Study"


def test_accepting_a_download_creates_a_linked_goal_without_process_links(store, server) -> None:
    server.add("r-1", "독서", minutes=30, weekdays=(5, 6), revision=3)

    result = apply_choices(store, server, _plan(store, server), [remote_key("r-1")])

    (goal,) = store.list_goals()
    assert result.downloaded == 1
    assert (goal.name, goal.daily_target_minutes, goal.weekdays, goal.processes, goal.sites) == (
        "독서",
        30,
        frozenset({5, 6}),
        (),
        (),
    )
    assert (store.sync_links()[0].remote_id, store.sync_links()[0].remote_revision) == ("r-1", 3)


def test_an_unchecked_download_is_simply_not_brought_over(store, server) -> None:
    server.add("r-1", "독서")

    result = apply_choices(store, server, _plan(store, server), [])

    assert store.list_goals() == [] and result.downloaded == 0


def test_keys_that_are_not_in_the_plan_are_ignored(store, server) -> None:
    store.create(**goal_fields())

    result = apply_choices(store, server, _plan(store, server), ["local:999", "remote:nope", "garbage"])

    assert (result.uploaded, result.merged, result.downloaded, result.errors) == (0, 0, 0, ())


def test_a_server_that_refuses_one_goal_does_not_stop_the_others(store, server) -> None:
    first = store.create(**goal_fields(name="A"))
    second = store.create(**goal_fields(name="B"))
    plan = _plan(store, server)
    server.add("r-clash", "A")  # 계획을 만든 뒤 다른 기기에서 같은 이름을 만들었다
    ids = iter(["r-1", "r-2"])

    result = apply_choices(store, server, plan, [local_key(first.id), local_key(second.id)], new_id=lambda: next(ids))

    assert result.uploaded == 1 and len(result.errors) == 1
    assert result.errors[0][0] == local_key(first.id) and "같은 이름" in result.errors[0][1]
    states = {link.goal_id: link for link in store.sync_links()}
    assert states[first.id].state == "local_only" and states[first.id].remote_id is None
    assert states[second.id].remote_id == "r-2"


def test_a_goal_that_fails_to_upload_for_other_reasons_stays_queued_for_the_agent(store, server) -> None:
    goal = store.create(**goal_fields())
    server.limit = 0
    plan = _plan(store, server)

    result = apply_choices(store, server, plan, [local_key(goal.id)])

    assert len(result.errors) == 1 and "20개" in result.errors[0][1]
    assert store.sync_links()[0].state == "sync" and store.sync_links()[0].remote_id is None  # 에이전트가 다시 시도한다


def test_a_dropped_connection_propagates_and_leaves_a_resumable_state(store, server) -> None:
    goal = store.create(**goal_fields())
    plan = _plan(store, server)
    server.unreachable = True

    with pytest.raises(ServerUnreachable):
        apply_choices(store, server, plan, [local_key(goal.id)])

    link = store.sync_links()[0]
    assert link.state == "sync" and link.remote_id is None
    assert store.get_meta(META_SYNC_ENABLED) == "1"


def test_a_download_that_would_collide_with_a_local_name_is_reported(store, server) -> None:
    server.add("r-1", "독서")
    plan = _plan(store, server)
    store.create(**goal_fields(name="독서"))  # 계획 뒤에 같은 이름을 이 PC에서 만들었다

    result = apply_choices(store, server, plan, [remote_key("r-1")])

    assert result.downloaded == 0 and len(result.errors) == 1
