from datetime import UTC, datetime, timedelta

import pytest

from common.updates import (
    RELEASES_PAGE,
    UpdateChecker,
    UpdateCheckFailed,
    newest_release,
    parse_version,
)


def release(tag, *, prerelease=False, draft=False, url=None):
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "html_url": url or f"{RELEASES_PAGE}/tag/{tag}",
        "published_at": "2026-11-25T00:00:00Z",
    }


def test_semver_order_including_prereleases() -> None:
    ordered = ["1.0.0-alpha", "1.0.0-beta.2", "1.0.0-beta.10", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.1.0", "2.0.0"]
    versions = [parse_version(text) for text in ordered]
    assert all(versions[i] < versions[i + 1] for i in range(len(versions) - 1))
    assert sorted(reversed(versions)) == versions


def test_versions_are_parsed_from_tags_and_the_dev_label() -> None:
    assert str(parse_version("v1.0.0-beta.2")) == "1.0.0-beta.2"
    assert str(parse_version("1.0.0-beta.2 (개발)")) == "1.0.0-beta.2"
    assert str(parse_version("1.2.3+build.5")) == "1.2.3"
    for bad in ("1.0", "01.0.0", "1.0.0-", "latest", "", "알 수 없음"):
        assert parse_version(bad) is None, bad


def test_a_stable_user_is_told_only_about_stable_releases() -> None:
    current = parse_version("1.0.0")
    releases = [release("v1.1.0-beta.1", prerelease=True), release("v1.0.1"), release("v1.0.2-rc.1")]
    assert newest_release(releases, current)["version"] == "1.0.1"


def test_a_prerelease_user_is_told_about_the_newest_including_prereleases() -> None:
    current = parse_version("1.0.0-beta.2")
    releases = [release("v1.0.0-beta.3", prerelease=True), release("v1.0.0-beta.10", prerelease=True), release("v0.9.0")]
    assert newest_release(releases, current)["version"] == "1.0.0-beta.10"
    assert newest_release([*releases, release("v1.0.0")], current)["version"] == "1.0.0"


def test_nothing_newer_drafts_and_bad_tags_are_ignored() -> None:
    current = parse_version("1.0.0-beta.2")
    assert newest_release([release("v1.0.0-beta.2"), release("v1.0.0-beta.1")], current) is None
    assert newest_release([release("v9.0.0", draft=True), release("nightly"), {"tag_name": 5}, "x"], current) is None
    with pytest.raises(ValueError):
        newest_release({"message": "rate limited"}, current)


def test_only_this_repositorys_release_pages_are_offered() -> None:
    current = parse_version("1.0.0")
    found = newest_release([release("v1.0.1", url="https://evil.example/download")], current)
    assert found["url"] == RELEASES_PAGE


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 25, 3, 0, tzinfo=UTC)


def checker(tmp_path, releases, *, current="1.0.0-beta.2", supported=True, clock=None):
    calls = []

    def fetch():
        calls.append(1)
        if isinstance(releases, Exception):
            raise releases
        return releases

    clock = clock or Clock()
    made = UpdateChecker(tmp_path / "update-check.json", current, supported=supported, fetch=fetch, now=lambda: clock.now)
    return made, calls, clock


def test_github_is_asked_at_most_once_a_day_and_the_result_is_remembered(tmp_path) -> None:
    made, calls, clock = checker(tmp_path, [release("v1.0.0")])

    first = made.state()
    assert first["available"] is True and first["latest"]["version"] == "1.0.0"
    assert made.state()["available"] is True
    assert len(calls) == 1
    clock.now += timedelta(hours=25)
    made.state()
    assert len(calls) == 2
    made.state(force=True)
    assert len(calls) == 3


def test_a_failed_check_keeps_the_last_answer_and_waits_for_the_next_day(tmp_path) -> None:
    made, calls, clock = checker(tmp_path, [release("v1.0.0")])
    made.state()
    made._fetch = lambda: (_ for _ in ()).throw(UpdateCheckFailed("URLError"))
    clock.now += timedelta(hours=25)

    state = made.state()

    assert state["available"] is True and state["error"] and "URLError" in state["error"]


def test_turning_the_check_off_stops_asking(tmp_path) -> None:
    made, calls, _ = checker(tmp_path, [release("v1.0.0")])
    assert made.set_enabled(False)["enabled"] is False
    assert made.state(force=True)["available"] is False
    assert calls == []
    assert made.set_enabled(True)["available"] is True


def test_the_dev_checkout_does_not_check(tmp_path) -> None:
    made, calls, _ = checker(tmp_path, [release("v1.0.0")], supported=False)
    state = made.state(force=True)
    assert (state["supported"], state["enabled"], state["available"]) == (False, False, False)
    assert calls == []


def test_a_remembered_version_that_is_already_installed_is_not_announced(tmp_path) -> None:
    made, _, clock = checker(tmp_path, [release("v1.0.0-beta.3", prerelease=True)])
    assert made.state()["latest"]["version"] == "1.0.0-beta.3"
    upgraded, calls, _ = checker(tmp_path, [release("v1.0.0-beta.3", prerelease=True)], current="1.0.0-beta.3", clock=clock)
    assert upgraded.state()["available"] is False  # 같은 캐시를 읽어도 지금 버전이 그 버전이다
    assert calls == []  # 같은 채널이고 하루가 안 지났다 — 다시 묻지 않는다


def test_a_broken_cache_file_is_treated_as_empty(tmp_path) -> None:
    (tmp_path / "update-check.json").write_text("{not json", encoding="utf-8")
    made, calls, _ = checker(tmp_path, [release("v1.0.0")])
    assert made.state()["available"] is True and calls == [1]


def test_dismissing_a_version_is_remembered_across_restarts(tmp_path) -> None:
    made, _, _ = checker(tmp_path, [release("v1.0.0")])
    made.state()
    assert made.dismiss("1.0.0")["dismissed"] == "1.0.0"
    reopened, _, _ = checker(tmp_path, [release("v1.0.0")])
    assert reopened.state()["dismissed"] == "1.0.0"  # 앱을 다시 열어도(화면의 저장소가 바뀌어도) 남는다
    with pytest.raises(ValueError):
        made.dismiss("latest")


def test_settings_that_could_not_be_saved_are_reported_not_pretended(tmp_path) -> None:
    from common.updates import UpdateSettingsFailed

    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    made = UpdateChecker(blocker / "update-check.json", "1.0.0-beta.2", supported=True, fetch=lambda: [])
    with pytest.raises(UpdateSettingsFailed):
        made.set_enabled(False)
    with pytest.raises(UpdateSettingsFailed):
        made.dismiss("1.0.0")


def test_a_prerelease_remembered_on_the_beta_channel_is_not_shown_after_installing_a_stable_version(tmp_path) -> None:
    beta, _, clock = checker(tmp_path, [release("v1.1.0-beta.1", prerelease=True)])
    assert beta.state()["latest"]["version"] == "1.1.0-beta.1"

    # 같은 날 1.0.0(정식)을 설치했다 — 기억해 둔 시험 버전은 알리지 않고, 채널이 바뀌었으니 정식 채널로 다시 묻는다
    stable, calls, _ = checker(tmp_path, [release("v1.1.0-beta.1", prerelease=True), release("v1.0.1")], current="1.0.0", clock=clock)
    state = stable.state()
    assert calls == [1]
    assert state["latest"]["version"] == "1.0.1"
