import json
import sqlite3
from pathlib import Path

from chromium.browsers import BROWSER_BY_PROCESS

from recorder.browser_site import (
    BrowserSiteResolver,
    ParsedTitle,
    SiteTracker,
    parse_browser_title,
    title_candidates,
)

PROFILES = frozenset({"개인", "업무"})
CHROME = BROWSER_BY_PROCESS["chrome.exe"]
EDGE = BROWSER_BY_PROCESS["msedge.exe"]


def _parse(title: str, browser=CHROME) -> ParsedTitle | None:
    return parse_browser_title(title, browser.title_labels, PROFILES)


def test_parses_plain_chrome_title() -> None:
    assert _parse("뉴스 - Google Chrome") == ParsedTitle("뉴스", None)


def test_parses_title_with_profile_name_on_either_side() -> None:
    assert _parse("뉴스 - 개인 - Chrome") == ParsedTitle("뉴스", "개인")
    assert _parse("뉴스 - Google Chrome - 업무") == ParsedTitle("뉴스", "업무")


def test_keeps_separators_inside_the_page_title() -> None:
    """페이지 제목에 " - "가 있어도 뒤의 브라우저/프로필만 떼어낸다."""
    assert _parse("A - B - C - Google Chrome") == ParsedTitle("A - B - C", None)
    # 프로필 이름이 아닌 꼬리는 페이지 제목의 일부다.
    assert _parse("A - 개인정보 - Chrome") == ParsedTitle("A - 개인정보", None)


def test_rejects_titles_of_other_apps_or_other_browsers_and_empty_pages() -> None:
    assert _parse("메모장") is None
    assert _parse(" - Google Chrome") is None
    # 같은 제목이라도 다른 브라우저의 표기는 이 브라우저의 것으로 보지 않는다.
    assert _parse("뉴스 - Microsoft Edge") is None
    assert _parse("뉴스 - Google Chrome", EDGE) is None


def test_edge_title_with_an_invisible_character_in_the_browser_name() -> None:
    """Edge는 "Microsoft Edge" 사이에 보이지 않는 글자(zero-width space)를 넣는다."""
    assert _parse("뉴스 - Microsoft​ Edge", EDGE) == ParsedTitle("뉴스", None)
    assert _parse("뉴스 - 개인 - Microsoft​ Edge", EDGE) == ParsedTitle("뉴스", "개인")


def test_other_chromium_browsers_use_their_own_label() -> None:
    brave = BROWSER_BY_PROCESS["brave.exe"]
    vivaldi = BROWSER_BY_PROCESS["vivaldi.exe"]

    assert _parse("뉴스 - Brave", brave) == ParsedTitle("뉴스", None)
    assert _parse("뉴스 - Vivaldi", vivaldi) == ParsedTitle("뉴스", None)


def test_edge_multi_tab_suffix_is_removed_from_the_page_title() -> None:
    """Edge는 탭이 여러 개면 제목 뒤에 "외 페이지 N개"를 붙인다(방문 기록 제목에는 없다)."""
    assert _parse("뉴스 외 페이지 3개 - Microsoft\u200b Edge", EDGE) == ParsedTitle("뉴스", None)
    assert _parse("News and 2 more pages - Microsoft\u200b Edge", EDGE) == ParsedTitle("News", None)
    assert _parse("News and 1 more page - 개인 - Microsoft\u200b Edge", EDGE) == ParsedTitle(
        "News", "개인"
    )
    # 페이지 제목이 우연히 비슷한 글로 끝나지 않으면 건드리지 않는다.
    assert _parse("페이지 3개 정리 - Google Chrome") == ParsedTitle("페이지 3개 정리", None)


def test_title_candidates_also_offer_the_title_without_an_unknown_profile_label() -> None:
    """Local State의 프로필 이름과 다르게 표시된 프로필 이름("개인")은 후보를 하나 더 만든다."""
    plain = title_candidates("뉴스 - Google Chrome", CHROME.title_labels, frozenset())
    assert [c.page for c in plain] == ["뉴스"]

    with_label = title_candidates(
        "뉴스 외 페이지 2개 - 개인 - Microsoft\u200b Edge", EDGE.title_labels, frozenset({"프로필 1"})
    )
    assert [c.page for c in with_label] == ["뉴스 외 페이지 2개 - 개인", "뉴스"]

    assert title_candidates("메모장", CHROME.title_labels, frozenset()) == []


def _write_browser(
    root: Path, profiles: dict[str, str], visits: dict[str, list[tuple[str, str, int]]]
) -> None:
    """가짜 브라우저 사용자 데이터 폴더. visits: {폴더: [(제목, URL, 방문 시각)]}."""
    root.mkdir(parents=True, exist_ok=True)
    info = {folder: {"name": name} for folder, name in profiles.items()}
    (root / "Local State").write_text(
        json.dumps({"profile": {"info_cache": info}}), encoding="utf-8"
    )
    for folder, rows in visits.items():
        (root / folder).mkdir(exist_ok=True)
        conn = sqlite3.connect(root / folder / "History")
        conn.execute("CREATE TABLE urls (url TEXT, title TEXT, last_visit_time INTEGER)")
        conn.executemany("INSERT INTO urls VALUES (?, ?, ?)", [(u, t, v) for t, u, v in rows])
        conn.commit()
        conn.close()


def test_resolver_finds_the_most_recent_visit_for_the_title(tmp_path) -> None:
    _write_browser(
        tmp_path,
        {"Default": "개인"},
        {
            "Default": [
                ("뉴스", "https://old.example.com/a", 100),
                ("뉴스", "https://www.news.example.com/b?q=1", 200),
                ("다른 글", "https://other.example.com/", 300),
            ]
        },
    )
    resolver = BrowserSiteResolver(CHROME, tmp_path)
    try:
        assert resolver.resolve("뉴스 - 개인 - Chrome") == "news.example.com"
        assert resolver.resolve("뉴스 - Google Chrome") == "news.example.com"
        assert resolver.resolve("기록에 없는 페이지 - Google Chrome") is None
        assert resolver.resolve("메모장") is None
    finally:
        resolver.close()


def test_resolver_uses_only_the_profile_named_in_the_title(tmp_path) -> None:
    _write_browser(
        tmp_path,
        {"Default": "개인", "Profile 1": "업무"},
        {
            "Default": [("보고서", "https://personal.example.com/", 500)],
            "Profile 1": [("보고서", "https://work.example.com/", 100)],
        },
    )
    resolver = BrowserSiteResolver(CHROME, tmp_path)
    try:
        assert resolver.resolve("보고서 - 업무 - Chrome") == "work.example.com"
        # 프로필을 모르면 방문이 가장 최근인 쪽을 쓴다.
        assert resolver.resolve("보고서 - Google Chrome") == "personal.example.com"
    finally:
        resolver.close()


def test_resolver_reads_an_edge_profile_with_edge_labels(tmp_path) -> None:
    _write_browser(
        tmp_path, {"Default": "개인"}, {"Default": [("뉴스", "https://news.example.com/", 1)]}
    )
    resolver = BrowserSiteResolver(EDGE, tmp_path)
    try:
        assert resolver.resolve("뉴스 - 개인 - Microsoft​ Edge") == "news.example.com"
        assert resolver.resolve("뉴스 - Google Chrome") is None  # Edge의 제목 표기가 아니다
    finally:
        resolver.close()


def test_resolver_finds_an_edge_page_despite_suffix_and_unknown_profile_label(tmp_path) -> None:
    """실제 Edge 제목 모양: "제목 외 페이지 N개 - 개인 - Microsoft Edge"(Local State 이름은 다름)."""
    _write_browser(
        tmp_path,
        {"Default": "프로필 1"},
        {"Default": [("뉴스", "https://news.example.com/a", 1)]},
    )
    resolver = BrowserSiteResolver(EDGE, tmp_path)
    try:
        assert (
            resolver.resolve("뉴스 외 페이지 3개 - 개인 - Microsoft\u200b Edge") == "news.example.com"
        )
    finally:
        resolver.close()


def test_exact_page_title_wins_over_the_profile_label_guess(tmp_path) -> None:
    """"A - B" 제목이 방문 기록에 그대로 있으면 "B"를 프로필로 보고 떼어 낸 "A"를 쓰지 않는다."""
    _write_browser(
        tmp_path,
        {"Default": "개인"},
        {
            "Default": [
                ("A", "https://short.example.com/", 900),
                ("A - B", "https://exact.example.com/", 100),
            ]
        },
    )
    resolver = BrowserSiteResolver(CHROME, tmp_path)
    try:
        assert resolver.resolve("A - B - Google Chrome") == "exact.example.com"
    finally:
        resolver.close()


def test_resolver_copies_history_only_when_it_changed(tmp_path) -> None:
    _write_browser(
        tmp_path, {"Default": "개인"}, {"Default": [("뉴스", "https://a.example.com/", 1)]}
    )
    resolver = BrowserSiteResolver(CHROME, tmp_path)
    try:
        assert resolver.resolve("뉴스 - Google Chrome") == "a.example.com"
        first_copy = resolver._copies["Default"][2]
        first_mtime = first_copy.stat().st_mtime_ns

        assert resolver.resolve("뉴스 - Google Chrome") == "a.example.com"
        assert first_copy.stat().st_mtime_ns == first_mtime  # 다시 복사하지 않았다

        conn = sqlite3.connect(tmp_path / "Default" / "History")
        conn.execute("INSERT INTO urls VALUES ('https://b.example.com/', '새 글', 9)")
        conn.commit()
        conn.close()

        assert resolver.resolve("새 글 - Google Chrome") == "b.example.com"
    finally:
        resolver.close()


def test_resolver_close_removes_the_history_copies(tmp_path) -> None:
    _write_browser(
        tmp_path, {"Default": "개인"}, {"Default": [("뉴스", "https://a.example.com/", 1)]}
    )
    resolver = BrowserSiteResolver(CHROME, tmp_path)
    resolver.resolve("뉴스 - Google Chrome")
    work_dir = resolver._work_dir
    assert work_dir.exists()

    resolver.close()

    assert not work_dir.exists()


def test_resolver_survives_a_missing_or_broken_history(tmp_path) -> None:
    _write_browser(tmp_path, {"Default": "개인", "Profile 1": "업무"}, {"Default": []})
    (tmp_path / "Profile 1").mkdir()
    (tmp_path / "Profile 1" / "History").write_bytes(b"not a sqlite file")
    resolver = BrowserSiteResolver(CHROME, tmp_path)
    try:
        assert resolver.resolve("뉴스 - Google Chrome") is None
    finally:
        resolver.close()


class _FakeResolver:
    def __init__(self, result: str | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.closed = False

    def resolve(self, _title: str) -> str | None:
        if self.error:
            raise self.error
        return self.result

    def close(self) -> None:
        self.closed = True


def test_tracker_only_looks_up_supported_browsers_and_counts_matches() -> None:
    tracker = SiteTracker({"chrome.exe": _FakeResolver("news.example.com")})  # type: ignore[dict-item]

    assert tracker.site_for("Code.exe", "main.py - Code") is None
    assert tracker.site_for("chrome.exe", None) is None
    assert tracker.site_for("chrome.exe", "뉴스 - Google Chrome") == "news.example.com"
    assert (tracker.browser_ticks, tracker.matched_ticks) == (2, 1)


def test_tracker_knows_which_processes_are_supported_browsers() -> None:
    tracker = SiteTracker({})

    assert all(tracker.is_browser(name) for name in ("chrome.exe", "msedge.exe", "brave.exe"))
    assert not tracker.is_browser("firefox.exe")
    assert not tracker.is_browser(None)


def test_tracker_uses_a_separate_resolver_per_browser() -> None:
    tracker = SiteTracker(
        {
            "chrome.exe": _FakeResolver("from-chrome.example.com"),  # type: ignore[dict-item]
            "msedge.exe": _FakeResolver("from-edge.example.com"),  # type: ignore[dict-item]
        }
    )

    assert tracker.site_for("chrome.exe", "t") == "from-chrome.example.com"
    assert tracker.site_for("msedge.exe", "t") == "from-edge.example.com"


def test_tracker_swallows_resolver_errors() -> None:
    tracker = SiteTracker({"chrome.exe": _FakeResolver(error=RuntimeError("boom"))})  # type: ignore[dict-item]

    assert tracker.site_for("chrome.exe", "뉴스 - Google Chrome") is None
    assert (tracker.browser_ticks, tracker.matched_ticks) == (1, 0)


def test_tracker_close_closes_every_resolver() -> None:
    resolvers = {"chrome.exe": _FakeResolver(), "msedge.exe": _FakeResolver()}
    SiteTracker(resolvers).close()  # type: ignore[arg-type]

    assert all(resolver.closed for resolver in resolvers.values())


def test_tracker_removes_copies_left_by_a_crashed_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    stale = tmp_path / "whatever-log-history-leftover"
    stale.mkdir()
    (stale / "Default.db").write_bytes(b"old history copy")
    unrelated = tmp_path / "something-else"
    unrelated.mkdir()

    SiteTracker({})

    assert not stale.exists()
    assert unrelated.exists()


def test_creating_a_second_resolver_does_not_delete_the_first_ones_copies(tmp_path) -> None:
    """리졸버를 만들 때 오래된 복사본을 지우면 다른 브라우저의 작업 폴더가 지워진다."""
    _write_browser(
        tmp_path / "a", {"Default": "개인"}, {"Default": [("뉴스", "https://a.example.com/", 1)]}
    )
    first = BrowserSiteResolver(CHROME, tmp_path / "a")
    try:
        assert first.resolve("뉴스 - Google Chrome") == "a.example.com"
        second = BrowserSiteResolver(EDGE, tmp_path / "b")
        second.close()

        assert first._work_dir.exists()
        assert first.resolve("뉴스 - Google Chrome") == "a.example.com"
    finally:
        first.close()
