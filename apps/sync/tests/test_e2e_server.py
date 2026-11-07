"""실제 서버(wrangler dev 또는 `docker compose up server`)를 상대로 한 통합 시험.

서버가 떠 있고 시험용 토큰이 있을 때만 돈다(기본으로는 건너뛴다). 클라이언트 코드(cloud.ServerApi, goalsync, 에이전트)를
진짜 Worker와 D1에 대 보는 유일한 시험이라서, 가짜 서버가 실제 서버와 어긋났는지를 여기서 잡는다.

    # 서버: 호스트에서 `corepack pnpm exec wrangler dev --port 8790`(apps/server) 또는 `docker compose up server`
    # 토큰:  TOKEN=$(node apps/server/scripts/dev-token.mjs e2e@example.com)
    WHATEVER_LOG_E2E_SERVER=http://127.0.0.1:8790 WHATEVER_LOG_E2E_TOKEN=$TOKEN uv run pytest apps/sync/tests/test_e2e_server.py

시험이 만든 목표는 끝에 지운다(서버에는 삭제 표시만 30일 남는다). 이름에 무작위 접미사를 붙여 다른 실행과 겹치지 않는다.
"""

import os
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from cloud import GoalConflict, NotAuthorized, ProgressEntry, ServerApi, ServerError
from goals import META_ACCOUNT_EMAIL, META_SYNC_ENABLED, GoalStore
from goalsync import KIND_DOWNLOAD, KIND_MERGE, KIND_UPLOAD, SyncState, apply_choices, build_plan, sync_once
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

SERVER = os.environ.get("WHATEVER_LOG_E2E_SERVER")
TOKEN = os.environ.get("WHATEVER_LOG_E2E_TOKEN")
EMAIL = "e2e@example.com"

pytestmark = pytest.mark.skipif(
    not (SERVER and TOKEN), reason="WHATEVER_LOG_E2E_SERVER와 WHATEVER_LOG_E2E_TOKEN이 있을 때만(실제 서버가 필요하다)"
)

TODAY = datetime.now().astimezone().date()


@pytest.fixture
def api():
    client = ServerApi(SERVER, TOKEN)
    yield client
    # 이 시험이 만든 목표를 모두 지운다(다른 목표는 건드리지 않는다).
    for goal in client.list_goals():
        if not goal.deleted and (goal.name or "").startswith("e2e-"):
            client.delete_goal(goal.id)


@pytest.fixture
def suffix() -> str:
    return uuid.uuid4().hex[:8]


def _store(tmp_path, name):
    return GoalStore(tmp_path / f"{name}.db")


def _fields(name, **over):
    return {"name": name, "daily_target_minutes": 120, "weekdays": [0, 1, 2, 3, 4, 5, 6], "processes": [], **over}


def _recorder(path, process: str, ticks: int):
    """오늘 정오부터 15초 간격 틱(활성)을 ticks개 남긴 recorder.db."""
    conn = open_db(path)
    moment = datetime.combine(TODAY, time(12, 0)).astimezone()
    for _ in range(ticks + 1):
        save_tick(
            conn,
            TickSample(
                sampled_at=moment.astimezone(UTC),
                foreground_process=process,
                windowed_processes=frozenset({process}),
                seconds_since_last_input=0.0,
                foreground_site=None,
            ),
        )
        moment += timedelta(seconds=15)
    conn.close()
    return path


def _confirm_all(store, api, email=EMAIL):
    plan = build_plan(store, api.list_goals(), email)
    return plan, apply_choices(store, api, plan, [item.key for item in plan.items])


def test_the_token_works_and_a_bad_token_is_refused() -> None:
    assert ServerApi(SERVER, TOKEN).list_goals() is not None
    with pytest.raises(NotAuthorized):
        ServerApi(SERVER, "x" * 43).list_goals()


def test_confirming_uploads_the_goal_values_and_nothing_about_the_processes(tmp_path, api, suffix) -> None:
    name = f"e2e-공부-{suffix}"
    with _store(tmp_path, "a") as store:
        goal = store.create(**_fields(name, daily_target_minutes=90, weekdays=[0, 2], processes=["Secret-Process.exe"]))

        plan = build_plan(store, api.list_goals(), EMAIL)
        mine = [item for item in plan.items if item.name == name]
        assert [item.kind for item in mine] == [KIND_UPLOAD]
        result = apply_choices(store, api, plan, [mine[0].key])

        assert result.uploaded == 1 and result.errors == ()
        link = next(link for link in store.sync_links() if link.goal_id == goal.id)
        assert link.remote_id and link.remote_revision == 1
    (remote,) = [g for g in api.list_goals() if g.name == name]
    assert (remote.daily_target_minutes, remote.weekdays) == (90, frozenset({0, 2}))
    assert "Secret-Process" not in repr(api.list_goals())  # 서버가 돌려주는 어디에도 프로세스 이름이 없다


def test_a_second_device_sees_the_goal_and_can_merge_or_download_it(tmp_path, api, suffix) -> None:
    name = f"e2e-공유-{suffix}"
    with _store(tmp_path, "pc") as pc, _store(tmp_path, "laptop") as laptop, _store(tmp_path, "other") as other:
        pc.create(**_fields(name, daily_target_minutes=60, processes=["Code.exe"]))
        plan = build_plan(pc, api.list_goals(), EMAIL)
        apply_choices(pc, api, plan, [item.key for item in plan.items if item.name == name])

        # 같은 이름의 목표가 이미 있는 노트북: 합치기(서버 값으로 맞추고, 프로세스 연결은 노트북 것을 유지)
        laptop.create(**_fields(name.upper().replace("E2E", "e2e"), daily_target_minutes=30, processes=["Notepad.exe"]))
        merge_plan = build_plan(laptop, api.list_goals(), EMAIL)
        merge = [item for item in merge_plan.items if item.name.casefold() == name.casefold()]
        assert [item.kind for item in merge] == [KIND_MERGE]
        apply_choices(laptop, api, merge_plan, [merge[0].key])
        merged = laptop.list_goals()[0]
        assert merged.daily_target_minutes == 60 and merged.processes == ("Notepad.exe",)

        # 목표가 하나도 없는 세 번째 기기: 가져오기(프로세스 연결은 비어 있다)
        download_plan = build_plan(other, api.list_goals(), EMAIL)
        download = [item for item in download_plan.items if item.name.casefold() == name.casefold()]
        assert [item.kind for item in download] == [KIND_DOWNLOAD]
        apply_choices(other, api, download_plan, [download[0].key])
        (fetched,) = other.list_goals()
        assert (fetched.daily_target_minutes, fetched.processes) == (60, ())


def test_edits_deletes_and_conflicts_travel_between_devices(tmp_path, api, suffix) -> None:
    name = f"e2e-동기-{suffix}"
    recorder_db = tmp_path / "none.db"
    with (
        _store(tmp_path, "a") as a,
        _store(tmp_path, "b") as b,
        SyncState(tmp_path / "a-sync.db") as state_a,
        SyncState(tmp_path / "b-sync.db") as state_b,
    ):
        goal_a = a.create(**_fields(name, daily_target_minutes=60))
        plan = build_plan(a, api.list_goals(), EMAIL)
        apply_choices(a, api, plan, [item.key for item in plan.items if item.name == name])
        plan_b = build_plan(b, api.list_goals(), EMAIL)
        apply_choices(b, api, plan_b, [item.key for item in plan_b.items if item.name == name])
        goal_b = b.list_goals()[0]

        # 두 기기가 같은 revision에서 동시에 고친다: 먼저 올린 쪽이 서버에 반영되고, 늦은 쪽은 409를 받고 자기 값을 다시 올린다.
        a.update(goal_a.id, **_fields(name, daily_target_minutes=90))
        b.update(goal_b.id, **_fields(name, daily_target_minutes=15))
        first = sync_once(a, state_a, api, recorder_db, email=EMAIL, today=TODAY)
        second = sync_once(b, state_b, api, recorder_db, email=EMAIL, today=TODAY)
        assert (first.pushed, second.pushed) == (1, 1) and second.problems == []
        assert [g for g in api.list_goals() if g.name == name][0].daily_target_minutes == 15  # 늦게 올린 쪽의 값이 남는다

        # 먼저 올린 기기는 다음 주기에 서버 값을 받아 온다
        pulled = sync_once(a, state_a, api, recorder_db, email=EMAIL, today=TODAY)
        assert pulled.pulled == 1 and a.get(goal_a.id).daily_target_minutes == 15

        # 한 기기에서 지우면 서버에서 지워지고, 다른 기기는 지우지 않고 연결만 끊는다
        b.delete(goal_b.id)
        assert sync_once(b, state_b, api, recorder_db, email=EMAIL, today=TODAY).deleted == 1
        assert not [g for g in api.list_goals() if g.name == name and not g.deleted]
        after = sync_once(a, state_a, api, recorder_db, email=EMAIL, today=TODAY)
        assert after.unlinked == 1 and a.get(goal_a.id) is not None
        assert next(link for link in a.sync_links() if link.goal_id == goal_a.id).state == "local_only"


def test_progress_from_two_devices_is_summed_by_the_server(tmp_path, api, suffix) -> None:
    name = f"e2e-달성-{suffix}"
    with (
        _store(tmp_path, "a") as a,
        _store(tmp_path, "b") as b,
        SyncState(tmp_path / "a-sync.db") as state_a,
        SyncState(tmp_path / "b-sync.db") as state_b,
    ):
        a.create(**_fields(name, processes=["Code.exe"]))
        plan = build_plan(a, api.list_goals(), EMAIL)
        apply_choices(a, api, plan, [item.key for item in plan.items if item.name == name])
        plan_b = build_plan(b, api.list_goals(), EMAIL)
        apply_choices(b, api, plan_b, [item.key for item in plan_b.items if item.name == name])
        goal_b = b.list_goals()[0]
        b.update(goal_b.id, **_fields(name, processes=["Phone.app.exe"]))  # 이 기기에서 연결한 앱은 다르다

        db_a = _recorder(tmp_path / "a.db", "Code.exe", 40)  # 10분
        db_b = _recorder(tmp_path / "b.db", "Phone.app.exe", 80)  # 20분
        report_a = sync_once(a, state_a, api, db_a, email=EMAIL, today=TODAY)
        report_b = sync_once(b, state_b, api, db_b, email=EMAIL, today=TODAY)
        assert report_a.progress_sent >= 1 and report_b.progress_sent >= 1

    (remote,) = [g for g in api.list_goals() if g.name == name]
    (day,) = [d for d in api.get_progress(TODAY.isoformat(), TODAY.isoformat()) if d.goal_id == remote.id]
    assert (day.minutes, day.target_minutes, day.devices, day.percent) == (30, 120, 2, 25)


def test_the_servers_rules_surface_as_typed_errors(api, suffix) -> None:
    name = f"e2e-규칙-{suffix}"
    goal_id = str(uuid.uuid4())
    created = api.put_goal(goal_id, name=name, daily_target_minutes=10, weekdays=[0], base_revision=0)
    assert created.revision == 1

    with pytest.raises(GoalConflict) as stale:
        api.put_goal(goal_id, name=name, daily_target_minutes=20, weekdays=[0], base_revision=5)
    assert stale.value.code == "conflict" and stale.value.current.revision == 1

    with pytest.raises(GoalConflict) as duplicate:
        api.put_goal(str(uuid.uuid4()), name=name.upper(), daily_target_minutes=10, weekdays=[0], base_revision=0)
    assert duplicate.value.code == "duplicate_name"

    with pytest.raises(ServerError) as invalid:
        api.put_goal(str(uuid.uuid4()), name="", daily_target_minutes=10, weekdays=[0], base_revision=0)
    assert invalid.value.status == 400

    api.delete_goal(goal_id)
    with pytest.raises(GoalConflict) as gone:
        api.put_goal(goal_id, name=name, daily_target_minutes=20, weekdays=[0], base_revision=1)
    assert gone.value.code == "goal_deleted"

    # 삭제된 목표에 달성도를 보내면 무시되고, 서버 응답으로 알려 준다
    result = api.put_progress(str(uuid.uuid4()), [ProgressEntry(goal_id, TODAY.isoformat(), 5, 10)])
    assert result.accepted == 0 and result.ignored_goal_ids == (goal_id,)


def test_nothing_is_sent_before_the_user_confirms(tmp_path, api, suffix) -> None:
    name = f"e2e-대기-{suffix}"
    with _store(tmp_path, "a") as store, SyncState(tmp_path / "s.db") as state:
        store.create(**_fields(name))

        report = sync_once(store, state, api, tmp_path / "none.db", email=EMAIL, today=TODAY)

        assert report.skipped == "not_enabled"
        assert not [g for g in api.list_goals() if g.name == name]
        assert store.get_meta(META_SYNC_ENABLED) is None and store.get_meta(META_ACCOUNT_EMAIL) is None


def test_the_agent_entry_point_syncs_with_the_token_from_the_environment(tmp_path, api, suffix, monkeypatch) -> None:
    import sync_agent.__main__ as agent

    name = f"e2e-에이전트-{suffix}"
    goals_db = tmp_path / "goals.db"
    with GoalStore(goals_db) as store:
        goal = store.create(**_fields(name))
        store.set_sync_state(goal.id, "sync")
        store.set_meta(META_SYNC_ENABLED, "1")
    monkeypatch.setenv("WHATEVER_LOG_SERVER_URL", SERVER)
    monkeypatch.setenv("WHATEVER_LOG_TOKEN", TOKEN)

    code = agent.main(
        [
            "--once", "--token-from-env",
            "--goals-db", str(goals_db),
            "--db-path", str(tmp_path / "none.db"),
            "--state-db", str(tmp_path / "sync.db"),
            "--log-path", str(tmp_path / "sync.log"),
        ]
    )  # fmt: skip

    assert code == 0
    assert [g.name for g in api.list_goals() if g.name == name] == [name]
    with GoalStore(goals_db) as store:
        assert next(iter(store.sync_links())).remote_id is not None
