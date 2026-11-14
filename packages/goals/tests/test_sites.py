"""브라우저의 사이트(세부 페이지)를 목표에 연결하는 규칙: 검증, 겹침 방지, 저장, 마이그레이션, 수행 시간."""

import sqlite3
from datetime import UTC, date, datetime

import pytest

from goals import (
    Goal,
    GoalStore,
    GoalValidationError,
    SiteTarget,
    compute_progress,
    is_valid_domain,
    site_key,
    validate_goal,
)
from goals.store import SCHEMA_VERSION

NOW = "2026-11-05T00:00:00+00:00"


def _site(browser: str = "chrome.exe", domain: str = "youtube.com") -> dict[str, str]:
    return {"browser": browser, "domain": domain}


def _fields(**overrides):
    fields = {
        "name": "공부",
        "daily_target_minutes": 60,
        "weekdays": [0, 1, 2],
        "processes": [],
        "sites": [],
    }
    return {**fields, **overrides}


def _codes(error: GoalValidationError) -> set[tuple[str, str]]:
    return {(item.field, item.code) for item in error.errors}


@pytest.fixture
def store(tmp_path):
    with GoalStore(tmp_path / "goals.db", now=lambda: datetime(2026, 11, 5, 3, 0, tzinfo=UTC)) as opened:
        yield opened


# --- 검증 ---


def test_a_valid_site_is_accepted_and_keyed_by_browser_and_domain() -> None:
    spec = validate_goal(**_fields(sites=[_site("Chrome.exe", "youtube.com")]))
    assert spec.sites == ((SiteTarget("Chrome.exe", "youtube.com"), "chrome.exe/youtube.com"),)


@pytest.mark.parametrize(
    ("site", "code"),
    [
        ("not-an-object", "type"),
        ({"browser": "chrome.exe"}, "type"),
        ({"browser": "chrome.exe", "domain": "a.com", "extra": 1}, "type"),
        ({"browser": 1, "domain": "a.com"}, "type"),
        (_site(domain="YouTube.com"), "not_lowercase"),
        (_site(domain="www.youtube.com"), "invalid_domain"),
        (_site(domain=".youtube.com"), "invalid_domain"),
        (_site(domain="youtube.com."), "invalid_domain"),
        (_site(domain="you tube.com"), "invalid_characters"),
        (_site(domain="a.com/path"), "invalid_characters"),
        (_site(domain="user@a.com"), "invalid_characters"),
        (_site(domain="a\n.com"), "invalid_characters"),
        (_site(domain=""), "length"),
        (_site(domain="a" * 254), "length"),
        (_site(browser="chrome"), "not_exe"),
        (_site(browser="a/b.exe"), "invalid_characters"),
    ],
)
def test_malformed_sites_are_rejected_per_item(site, code) -> None:
    with pytest.raises(GoalValidationError) as caught:
        validate_goal(**_fields(sites=[site]))
    assert ("sites[0]", code) in _codes(caught.value)


def test_sites_must_be_a_list_with_a_limit() -> None:
    with pytest.raises(GoalValidationError) as caught:
        validate_goal(**_fields(sites="youtube.com"))
    assert ("sites", "type") in _codes(caught.value)
    with pytest.raises(GoalValidationError) as caught:
        validate_goal(**_fields(sites=[_site(domain=f"a{i}.com") for i in range(21)]))
    assert ("sites", "too_many") in _codes(caught.value)
    validate_goal(**_fields(sites=[_site(domain=f"a{i}.com") for i in range(20)]))


def test_duplicate_sites_are_rejected_ignoring_browser_case() -> None:
    with pytest.raises(GoalValidationError) as caught:
        validate_goal(**_fields(sites=[_site("chrome.exe"), _site("CHROME.EXE")]))
    assert ("sites[1]", "duplicate") in _codes(caught.value)
    # 같은 도메인이라도 브라우저가 다르면 다른 대상이다
    validate_goal(**_fields(sites=[_site("chrome.exe"), _site("msedge.exe")]))


def test_a_browser_and_its_own_sites_cannot_be_linked_together() -> None:
    with pytest.raises(GoalValidationError) as caught:
        validate_goal(**_fields(processes=["chrome.exe"], sites=[_site("Chrome.exe")]))
    assert ("sites[0]", "overlaps_process") in _codes(caught.value)
    # 다른 브라우저의 사이트는 상관없다
    validate_goal(**_fields(processes=["chrome.exe"], sites=[_site("msedge.exe")]))


def test_known_browsers_and_known_sites_restrict_what_can_be_linked() -> None:
    known = {("chrome.exe", "youtube.com")}
    validate_goal(**_fields(sites=[_site()]), known_sites=known, known_browsers={"chrome.exe"})
    with pytest.raises(GoalValidationError) as caught:
        validate_goal(**_fields(sites=[_site(domain="never.com")]), known_sites=known)
    assert ("sites[0]", "unknown_site") in _codes(caught.value)
    with pytest.raises(GoalValidationError) as caught:
        validate_goal(**_fields(sites=[_site("Code.exe")]), known_browsers={"chrome.exe"})
    assert ("sites[0]", "unknown_browser") in _codes(caught.value)


def test_domain_validity_matches_what_the_recorder_writes() -> None:
    assert is_valid_domain("youtube.com")
    assert is_valid_domain("::1")  # IPv6 호스트도 기록된다
    assert not is_valid_domain("www.youtube.com")
    assert not is_valid_domain(None)


def test_site_key_is_case_insensitive_and_unambiguous() -> None:
    assert site_key("Chrome.exe", "a.com") == site_key("chrome.exe", "a.com")
    assert site_key("a.exe", "b.com") != site_key("a.exe", "c.com")


# --- 저장 ---


def test_sites_are_stored_and_read_back_in_key_order(store) -> None:
    goal = store.create(**_fields(sites=[_site("msedge.exe", "b.com"), _site("chrome.exe", "z.com"), _site("chrome.exe", "a.com")]))
    assert goal.sites == (
        SiteTarget("chrome.exe", "a.com"),
        SiteTarget("chrome.exe", "z.com"),
        SiteTarget("msedge.exe", "b.com"),
    )
    assert store.get(goal.id).sites == goal.sites
    updated = store.update(goal.id, **_fields(sites=[_site("chrome.exe", "a.com")]))
    assert updated.sites == (SiteTarget("chrome.exe", "a.com"),)


def test_a_site_belongs_to_one_goal_only(store) -> None:
    store.create(**_fields(name="A", sites=[_site()]))
    with pytest.raises(GoalValidationError) as caught:
        store.create(**_fields(name="B", sites=[_site("CHROME.exe")]))
    assert ("sites", "already_linked") in _codes(caught.value)


def test_a_browser_cannot_be_linked_whole_in_one_goal_and_by_site_in_another(store) -> None:
    store.create(**_fields(name="A", processes=["chrome.exe"]))
    with pytest.raises(GoalValidationError) as caught:
        store.create(**_fields(name="B", sites=[_site()]))
    assert ("sites", "overlaps_process") in _codes(caught.value)

    other = store.create(**_fields(name="C", sites=[_site("msedge.exe", "a.com")]))
    with pytest.raises(GoalValidationError) as caught:
        store.update(other.id, **_fields(name="C", processes=["msedge.exe"], sites=[_site("msedge.exe", "a.com")]))
    # 같은 목표 안의 겹침은 사이트 쪽 오류로 알린다(다른 목표와의 겹침인 overlaps_site가 아니다)
    assert _codes(caught.value) == {("sites[0]", "overlaps_process")}

    with pytest.raises(GoalValidationError) as caught:
        store.create(**_fields(name="D", processes=["msedge.exe"]))
    assert ("processes", "overlaps_site") in _codes(caught.value)


def test_conflicts_are_reported_even_when_another_field_is_malformed(store) -> None:
    store.create(**_fields(name="A", sites=[_site()]))
    with pytest.raises(GoalValidationError) as caught:
        store.create(**_fields(name="B", daily_target_minutes="abc", sites=[_site()]))
    assert {("daily_target_minutes", "type"), ("sites", "already_linked")} <= _codes(caught.value)


def test_the_database_enforces_one_goal_per_site(tmp_path) -> None:
    path = tmp_path / "goals.db"
    with GoalStore(path) as store:
        store.create(**_fields(name="A", sites=[_site()]))
        other = store.create(**_fields(name="B"))
    raw = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(
            "INSERT INTO goal_targets (goal_id, kind, name, name_key) VALUES (?, 'site', 'CHROME.EXE/youtube.com', 'chrome.exe/youtube.com')",
            (other.id,),
        )


def test_snapshots_keep_the_sites_of_that_day(store) -> None:
    goal = store.create(**_fields(sites=[_site()], weekdays=list(range(7))))
    (snapshot,) = store.snapshot_today(date(2026, 11, 5))
    assert snapshot.sites == (SiteTarget("chrome.exe", "youtube.com"),)
    store.update(goal.id, **_fields(sites=[]))
    assert store.snapshots(date(2026, 11, 5))[0].sites == (SiteTarget("chrome.exe", "youtube.com"),)


def test_a_version_1_database_is_migrated_and_keeps_its_links(tmp_path) -> None:
    path = tmp_path / "goals.db"
    with GoalStore(path) as store:
        store.create(**_fields(name="A", processes=["Code.exe"]))
    # 1버전 모양으로 되돌린다: 종류가 process뿐인 CHECK와 user_version 1.
    raw = sqlite3.connect(path, isolation_level=None)
    raw.execute("PRAGMA foreign_keys = OFF")
    raw.execute("ALTER TABLE goal_targets RENAME TO t")
    raw.execute(
        "CREATE TABLE goal_targets (goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE, "
        "kind TEXT NOT NULL CHECK (kind IN ('process')), name TEXT NOT NULL, name_key TEXT NOT NULL, "
        "PRIMARY KEY (goal_id, kind, name_key), UNIQUE (kind, name_key))"
    )
    raw.execute("INSERT INTO goal_targets SELECT * FROM t")
    raw.execute("DROP TABLE t")
    raw.execute("PRAGMA user_version = 1")
    raw.close()

    with GoalStore(path) as store:
        (goal,) = store.list_goals()
        assert goal.processes == ("Code.exe",)
        updated = store.update(goal.id, **_fields(name="A", processes=["Code.exe"], sites=[_site()]))
        assert updated.sites == (SiteTarget("chrome.exe", "youtube.com"),)
    (version,) = sqlite3.connect(path).execute("PRAGMA user_version").fetchone()
    assert version == SCHEMA_VERSION == 4


# --- 수행 시간 ---


def _goal(goal_id: int, name: str, processes=(), sites=()) -> Goal:
    return Goal(
        id=goal_id,
        name=name,
        daily_target_minutes=60,
        weekdays=frozenset(range(7)),
        processes=tuple(processes),
        created_at=NOW,
        updated_at=NOW,
        sites=tuple(SiteTarget(*site) for site in sites),
    )


def test_a_goals_time_includes_its_sites() -> None:
    goals = [_goal(1, "공부", ["Code.exe"], [("chrome.exe", "docs.python.org")])]
    progress, summary = compute_progress(
        goals,
        {"Code.exe": 100.0, "chrome.exe": 9999.0},  # 브라우저 전체 시간은 사이트 연결에 섞이지 않는다
        {("chrome.exe", "docs.python.org"): 50.0, ("chrome.exe", "other.com"): 700.0},
    )
    assert progress[0].active_seconds == 150.0
    assert [(site.domain, site.active_seconds) for site in progress[0].sites] == [("docs.python.org", 50.0)]
    assert summary.active_seconds == 150.0


def test_site_matching_ignores_browser_case_and_unrecorded_sites_count_zero() -> None:
    goals = [_goal(1, "A", sites=[("Chrome.exe", "a.com"), ("chrome.exe", "none.com")])]
    progress, _ = compute_progress(goals, {}, {("chrome.EXE", "a.com"): 30.0})
    assert [site.active_seconds for site in progress[0].sites] == [30.0, 0.0]


def test_the_top_target_can_be_a_site_and_says_which_browser() -> None:
    goals = [_goal(1, "A", ["Code.exe"], [("chrome.exe", "a.com")])]
    _, summary = compute_progress(goals, {"Code.exe": 10.0}, {("chrome.exe", "a.com"): 20.0})
    assert (summary.top.process, summary.top.site, summary.top.active_seconds) == ("chrome.exe", "a.com", 20.0)
    _, summary = compute_progress(goals, {"Code.exe": 30.0}, {("chrome.exe", "a.com"): 20.0})
    assert (summary.top.process, summary.top.site) == ("Code.exe", None)


def test_no_site_time_keeps_the_summary_empty() -> None:
    _, summary = compute_progress([_goal(1, "A", sites=[("chrome.exe", "a.com")])], {}, {})
    assert summary.top is None
