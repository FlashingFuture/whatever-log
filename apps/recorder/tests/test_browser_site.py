import json
import sqlite3
from pathlib import Path

from recorder.browser_site import (
    ChromeSiteResolver,
    ParsedTitle,
    SiteTracker,
    parse_chrome_title,
)

PROFILES = frozenset({"개인", "업무"})


def test_parses_plain_chrome_title() -> None:
    assert parse_chrome_title("뉴스 - Google Chrome", PROFILES) == ParsedTitle("뉴스", None)


def test_parses_title_with_profile_name_on_either_side() -> None:
    assert parse_chrome_title("뉴스 - 개인 - Chrome", PROFILES) == ParsedTitle("뉴스", "개인")
    assert parse_chrome_title("뉴스 - Google Chrome - 업무", PROFILES) == ParsedTitle(
        "뉴스", "업무"
    )


def test_keeps_separators_inside_the_page_title() -> None:
    """페이지 제목에 " - "가 있어도 뒤의 브라우저/프로필만 떼어낸다."""
    assert parse_chrome_title("A - B - C - Google Chrome", PROFILES) == ParsedTitle(
        "A - B - C", None
    )
    # 프로필 이름이 아닌 꼬리는 페이지 제목의 일부다.
    assert parse_chrome_title("A - 개인정보 - Chrome", PROFILES) == ParsedTitle(
        "A - 개인정보", None
    )


def test_non_chrome_or_empty_titles_are_rejected() -> None:
    assert parse_chrome_title("메모장", PROFILES) is None
    assert parse_chrome_title("뉴스 - Microsoft Edge", PROFILES) is None
    assert parse_chrome_title(" - Google Chrome", PROFILES) is None


def _write_chrome(root: Path, profiles: dict[str, str], visits: dict[str, list[tuple[str, str, int]]]) -> None:
    """가짜 Chrome 사용자 데이터 폴더. visits: {폴더: [(제목, URL, 방문 시각)]}."""
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
    _write_chrome(
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
    resolver = ChromeSiteResolver(tmp_path)
    try:
        assert resolver.resolve("뉴스 - 개인 - Chrome") == "news.example.com"
        assert resolver.resolve("뉴스 - Google Chrome") == "news.example.com"
        assert resolver.resolve("기록에 없는 페이지 - Google Chrome") is None
        assert resolver.resolve("메모장") is None
    finally:
        resolver.close()


def test_resolver_uses_only_the_profile_named_in_the_title(tmp_path) -> None:
    _write_chrome(
        tmp_path,
        {"Default": "개인", "Profile 1": "업무"},
        {
            "Default": [("보고서", "https://personal.example.com/", 500)],
            "Profile 1": [("보고서", "https://work.example.com/", 100)],
        },
    )
    resolver = ChromeSiteResolver(tmp_path)
    try:
        assert resolver.resolve("보고서 - 업무 - Chrome") == "work.example.com"
        # 프로필을 모르면 방문이 가장 최근인 쪽을 쓴다.
        assert resolver.resolve("보고서 - Google Chrome") == "personal.example.com"
    finally:
        resolver.close()


def test_resolver_copies_history_only_when_it_changed(tmp_path) -> None:
    _write_chrome(tmp_path, {"Default": "개인"}, {"Default": [("뉴스", "https://a.example.com/", 1)]})
    resolver = ChromeSiteResolver(tmp_path)
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
    _write_chrome(tmp_path, {"Default": "개인"}, {"Default": [("뉴스", "https://a.example.com/", 1)]})
    resolver = ChromeSiteResolver(tmp_path)
    resolver.resolve("뉴스 - Google Chrome")
    work_dir = resolver._work_dir
    assert work_dir.exists()

    resolver.close()

    assert not work_dir.exists()


def test_resolver_survives_a_missing_or_broken_history(tmp_path) -> None:
    _write_chrome(tmp_path, {"Default": "개인", "Profile 1": "업무"}, {"Default": []})
    (tmp_path / "Profile 1").mkdir()
    (tmp_path / "Profile 1" / "History").write_bytes(b"not a sqlite file")
    resolver = ChromeSiteResolver(tmp_path)
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


def test_tracker_only_looks_up_chrome_and_counts_matches() -> None:
    tracker = SiteTracker(_FakeResolver("news.example.com"))  # type: ignore[arg-type]

    assert tracker.site_for("Code.exe", "main.py - Code") is None
    assert tracker.site_for("chrome.exe", None) is None
    assert tracker.site_for("chrome.exe", "뉴스 - Google Chrome") == "news.example.com"
    assert (tracker.chrome_ticks, tracker.matched_ticks) == (2, 1)


def test_tracker_swallows_resolver_errors() -> None:
    tracker = SiteTracker(_FakeResolver(error=RuntimeError("boom")))  # type: ignore[arg-type]

    assert tracker.site_for("chrome.exe", "뉴스 - Google Chrome") is None
    assert (tracker.chrome_ticks, tracker.matched_ticks) == (1, 0)


def test_tracker_close_closes_the_resolver() -> None:
    resolver = _FakeResolver()
    SiteTracker(resolver).close()  # type: ignore[arg-type]

    assert resolver.closed


def test_resolver_removes_copies_left_by_a_crashed_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    stale = tmp_path / "whatever-log-history-leftover"
    stale.mkdir()
    (stale / "Default.db").write_bytes(b"old history copy")
    unrelated = tmp_path / "something-else"
    unrelated.mkdir()

    resolver = ChromeSiteResolver(tmp_path / "chrome")
    try:
        assert not stale.exists()
        assert unrelated.exists()
    finally:
        resolver.close()
