import json
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from recorder.sampling import TickSample
from recorder.storage import open_db, save_tick

from hub.__main__ import _Handler
import hub.site_icons as site_icons_module
from hub.memory_cache import ImageMemoryCache
from hub.site_icons import (
    SITE_ICON_TTL_SECONDS,
    SiteIconStore,
    _pick_best,
    is_valid_domain,
)

_PNG = b"\x89PNG\r\n\x1a\n"


def _png(tag: str) -> bytes:
    return _PNG + tag.encode()


def _write_favicons(root: Path, folder: str, rows: list[tuple[str, str, int, int]]) -> None:
    """가짜 Favicons DB. rows: (page_url, PNG 태그, 너비, 갱신 시각)."""
    (root / folder).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / folder / "Favicons")
    conn.execute("CREATE TABLE icon_mapping (id INTEGER PRIMARY KEY, page_url TEXT, icon_id INTEGER)")
    conn.execute(
        "CREATE TABLE favicon_bitmaps (id INTEGER PRIMARY KEY, icon_id INTEGER, "
        "last_updated INTEGER, image_data BLOB, width INTEGER, height INTEGER)"
    )
    for index, (url, tag, width, updated) in enumerate(rows, start=1):
        conn.execute("INSERT INTO icon_mapping (page_url, icon_id) VALUES (?, ?)", (url, index))
        data = tag.encode() if tag.startswith("RAW:") else _png(tag)
        conn.execute(
            "INSERT INTO favicon_bitmaps (icon_id, last_updated, image_data, width, height) "
            "VALUES (?, ?, ?, ?, ?)",
            (index, updated, data, width, width),
        )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("domain", ["youtube.com", "docs.example.co.kr", "127.0.0.1", "a"])
def test_accepts_plain_domains(domain: str) -> None:
    assert is_valid_domain(domain)


@pytest.mark.parametrize(
    "domain", ["", "a b", "a/b", "a%b", "a_b.com", "Example.com", "-a.com", "a.com-", "x" * 254]
)
def test_rejects_anything_that_is_not_a_plain_lowercase_domain(domain: str) -> None:
    assert not is_valid_domain(domain)


def test_reads_the_icon_closest_to_the_preferred_size(tmp_path) -> None:
    _write_favicons(
        tmp_path,
        "Default",
        [
            ("https://www.news.example.com/a", "small", 16, 100),
            ("https://news.example.com/b", "big", 32, 100),
            ("https://other.example.com/", "other", 32, 100),
        ],
    )
    store = SiteIconStore([tmp_path])

    key, png = store.get("news.example.com")

    assert png == _png("big")
    assert len(key) == 32


def test_prefers_the_most_recently_updated_icon_across_profiles(tmp_path) -> None:
    _write_favicons(tmp_path, "Default", [("https://news.example.com/", "old", 32, 100)])
    _write_favicons(tmp_path, "Profile 1", [("http://news.example.com/", "new", 32, 900)])
    store = SiteIconStore([tmp_path])

    assert store.get("news.example.com")[1] == _png("new")


def test_returns_none_for_unknown_domains_and_non_png_data(tmp_path) -> None:
    _write_favicons(tmp_path, "Default", [("https://ico.example.com/", "RAW:not-a-png", 32, 1)])
    store = SiteIconStore([tmp_path])

    assert store.get("missing.example.com") is None
    assert store.get("ico.example.com") is None
    assert store.get("Bad_Domain") is None  # 도메인 모양이 아니면 Chrome 파일을 읽지도 않는다


def test_does_not_match_a_longer_domain_that_merely_contains_the_name(tmp_path) -> None:
    _write_favicons(tmp_path, "Default", [("https://notexample.com/", "other", 32, 1)])
    store = SiteIconStore([tmp_path])

    assert store.get("example.com") is None


def test_survives_missing_or_broken_favicon_files(tmp_path) -> None:
    (tmp_path / "Default").mkdir()
    (tmp_path / "Profile 1").mkdir()
    (tmp_path / "Profile 1" / "Favicons").write_bytes(b"not a sqlite file")
    store = SiteIconStore([tmp_path])

    assert store.get("news.example.com") is None


def test_caches_hits_in_memory_and_remembers_misses_briefly(tmp_path, monkeypatch) -> None:
    _write_favicons(tmp_path, "Default", [("https://news.example.com/", "x", 32, 1)])
    store = SiteIconStore([tmp_path])
    reads = []
    original = store._read_from_browsers
    monkeypatch.setattr(store, "_read_from_browsers", lambda d: (reads.append(d), original(d))[1])

    assert store.get("news.example.com") is not None
    assert store.get("news.example.com") is not None
    assert store.get("none.example.com") is None
    assert store.get("none.example.com") is None

    assert reads == ["news.example.com", "none.example.com"]


def test_finds_icons_of_pages_with_a_port(tmp_path) -> None:
    """도메인을 기록할 때 포트를 버리므로(localhost:3000 → localhost) 포트가 있는 페이지의 아이콘도 찾는다."""
    _write_favicons(
        tmp_path,
        "Default",
        [
            ("http://localhost:3000/app", "dev", 32, 1),
            ("https://www.example.com:8443/x", "secure", 32, 1),
        ],
    )
    store = SiteIconStore([tmp_path])

    assert store.get("localhost")[1] == _png("dev")
    assert store.get("example.com")[1] == _png("secure")


def test_pick_best_skips_rows_with_null_columns() -> None:
    """Chromium 스키마는 컬럼에 NULL을 허용한다 — 그런 행 때문에 예외가 나면 응답이 끊긴다."""
    good = (_png("good"), 16, 5)

    assert _pick_best([(None, 32, 9), (_png("a"), None, 9), (_png("b"), 32, None), good]) == _png(
        "good"
    )
    assert _pick_best([(None, None, None)]) is None
    assert _pick_best([]) is None


def test_a_broken_favicons_file_never_raises_out_of_the_store(tmp_path, monkeypatch) -> None:
    _write_favicons(tmp_path, "Default", [("https://a.example.com/", "x", 32, 1)])
    store = SiteIconStore([tmp_path])

    def boom(domain):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(store, "_read_from_browsers", boom)

    assert store.get("a.example.com") is None


def test_cached_icons_expire_so_a_cleared_history_disappears(tmp_path) -> None:
    clock = [1000.0]
    cache = ImageMemoryCache(ttl_seconds=SITE_ICON_TTL_SECONDS, clock=lambda: clock[0])
    _write_favicons(tmp_path, "Default", [("https://news.example.com/", "x", 32, 1)])
    store = SiteIconStore([tmp_path], cache)
    assert store.get("news.example.com") is not None

    (tmp_path / "Default" / "Favicons").unlink()  # 사용자가 브라우저 기록을 지웠다
    clock[0] += SITE_ICON_TTL_SECONDS - 1
    assert store.get("news.example.com") is not None  # 아직 메모리 캐시

    clock[0] += 2
    assert store.get("news.example.com") is None


def test_concurrent_requests_for_one_domain_read_the_browser_files_once(
    tmp_path, monkeypatch
) -> None:
    _write_favicons(tmp_path, "Default", [("https://news.example.com/", "x", 32, 1)])
    store = SiteIconStore([tmp_path])
    reads = []
    original = store._read_from_browsers

    def slow_read(domain):
        reads.append(domain)
        time.sleep(0.2)
        return original(domain)

    monkeypatch.setattr(store, "_read_from_browsers", slow_read)
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.get("news.example.com"))) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(reads) == 1
    assert all(result is not None for result in results)


def test_reads_each_bitmap_once_even_when_many_pages_share_an_icon(
    tmp_path, monkeypatch
) -> None:
    """같은 아이콘을 쓰는 페이지가 수천 개여도 비트맵 행이 페이지 수만큼 반복 적재되면 안 된다."""
    (tmp_path / "Default").mkdir()
    conn = sqlite3.connect(tmp_path / "Default" / "Favicons")
    conn.execute("CREATE TABLE icon_mapping (id INTEGER PRIMARY KEY, page_url TEXT, icon_id INTEGER)")
    conn.execute(
        "CREATE TABLE favicon_bitmaps (id INTEGER PRIMARY KEY, icon_id INTEGER, "
        "last_updated INTEGER, image_data BLOB, width INTEGER, height INTEGER)"
    )
    conn.execute(
        "INSERT INTO favicon_bitmaps (icon_id, last_updated, image_data, width, height) "
        "VALUES (1, 1, ?, 32, 32)",
        (_png("shared"),),
    )
    conn.executemany(
        "INSERT INTO icon_mapping (page_url, icon_id) VALUES (?, 1)",
        [(f"https://news.example.com/page/{i}",) for i in range(500)],
    )
    conn.commit()
    conn.close()
    store = SiteIconStore([tmp_path])
    rows_read = []
    original = site_icons_module._best_candidate

    def counting(rows):
        return original(row for row in rows if rows_read.append(1) is None)

    monkeypatch.setattr(site_icons_module, "_best_candidate", counting)

    assert store.get("news.example.com")[1] == _png("shared")
    assert len(rows_read) == 1


def test_copies_for_different_domains_are_limited_to_a_few_at_a_time(tmp_path, monkeypatch) -> None:
    _write_favicons(tmp_path, "Default", [(f"https://d{i}.example.com/", "x", 32, 1) for i in range(8)])
    store = SiteIconStore([tmp_path])
    running = []
    peak = []
    guard = threading.Lock()
    original = store._read_from_browsers

    def slow_read(domain):
        with guard:
            running.append(1)
            peak.append(len(running))
        time.sleep(0.1)
        try:
            return original(domain)
        finally:
            with guard:
                running.pop()

    monkeypatch.setattr(store, "_read_from_browsers", slow_read)
    threads = [threading.Thread(target=store.get, args=(f"d{i}.example.com",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max(peak) <= 2


def test_leaves_no_copy_of_the_favicons_behind(tmp_path, monkeypatch) -> None:
    import tempfile

    work = tmp_path / "tmp"
    work.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(work))
    _write_favicons(tmp_path / "chrome", "Default", [("https://news.example.com/", "x", 32, 1)])

    SiteIconStore([tmp_path / "chrome"]).get("news.example.com")

    assert list(work.iterdir()) == []


# --- HTTP 엔드포인트 ---

_TICK_AT = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)


def _save_site_ticks(db_path: Path, site: str | None) -> None:
    conn = open_db(db_path)
    for offset in (0, 15, 30):
        save_tick(
            conn,
            TickSample(
                sampled_at=_TICK_AT + timedelta(seconds=offset),
                foreground_process="chrome.exe",
                windowed_processes=frozenset({"chrome.exe"}),
                seconds_since_last_input=0.0,
                foreground_site=site if offset < 30 else None,
            ),
        )
    conn.close()


@pytest.fixture
def site_server(tmp_path):
    db_path = tmp_path / "recorder.db"
    _save_site_ticks(db_path, "news.example.com")
    _write_favicons(
        tmp_path / "chrome",
        "Default",
        [
            ("https://news.example.com/", "news", 32, 1),
            ("https://unrecorded.example.com/", "unrecorded", 32, 1),
        ],
    )
    _Handler.db_path = db_path
    _Handler.site_icon_store = SiteIconStore([tmp_path / "chrome"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def test_sites_endpoint_returns_usage_per_domain(site_server) -> None:
    query = urllib.parse.urlencode(
        {
            "start": _TICK_AT.isoformat(),
            "end": (_TICK_AT + timedelta(hours=1)).isoformat(),
            "process": "chrome.exe",
        }
    )

    with urllib.request.urlopen(f"{site_server}/api/sites?{query}", timeout=2) as response:
        payload = json.loads(response.read())

    assert payload["by_site"] == [
        {
            "domain": "news.example.com",
            "active_seconds": 30.0,
            "idle_seconds": 0.0,
            "total_seconds": 30.0,
        }
    ]


def test_sites_endpoint_rejects_missing_bounds_or_process(site_server) -> None:
    window = {
        "start": _TICK_AT.isoformat(),
        "end": (_TICK_AT + timedelta(hours=1)).isoformat(),
    }
    for query in ({}, window, {**window, "process": ""}):
        url = f"{site_server}/api/sites?{urllib.parse.urlencode(query)}"
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(url, timeout=2)
        assert exc_info.value.code == 400


def test_sites_endpoint_only_counts_the_requested_browser(site_server) -> None:
    query = urllib.parse.urlencode(
        {
            "start": _TICK_AT.isoformat(),
            "end": (_TICK_AT + timedelta(hours=1)).isoformat(),
            "process": "msedge.exe",
        }
    )

    with urllib.request.urlopen(f"{site_server}/api/sites?{query}", timeout=2) as response:
        assert json.loads(response.read())["by_site"] == []


def test_sites_endpoint_treats_a_pre_site_database_as_empty(tmp_path) -> None:
    """사이트 컬럼이 없는 옛 DB도 503이 아니라 빈 목록이어야 한다(hub는 읽기 전용)."""
    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(old_db)
    conn.execute(
        "CREATE TABLE ticks (id INTEGER PRIMARY KEY, sampled_at TEXT NOT NULL, "
        "foreground_process_id INTEGER, seconds_since_last_input REAL NOT NULL)"
    )
    conn.commit()
    conn.close()
    _Handler.db_path = old_db
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    query = urllib.parse.urlencode(
        {
            "start": _TICK_AT.isoformat(),
            "end": (_TICK_AT + timedelta(hours=1)).isoformat(),
            "process": "chrome.exe",
        }
    )
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/api/sites?{query}", timeout=2
        ) as response:
            assert json.loads(response.read())["by_site"] == []
    finally:
        server.shutdown()


def test_site_icon_endpoint_serves_png_with_cache_headers_and_304(
    site_server, ui_request
) -> None:
    url = f"{site_server}/api/site-icons/news.example.com"
    with urllib.request.urlopen(ui_request(url), timeout=2) as response:
        body, headers = response.read(), response.headers

    assert body == _png("news")
    assert headers["Content-Type"] == "image/png"
    assert f"max-age={SITE_ICON_TTL_SECONDS}" in headers["Cache-Control"]

    request = ui_request(url, **{"If-None-Match": headers["ETag"]})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=2)
    assert exc_info.value.code == 304


@pytest.mark.parametrize("domain", ["unrecorded.example.com", "missing.example.com", "..%2F..%2Fetc"])
def test_site_icon_endpoint_only_serves_domains_the_recorder_saw(
    site_server, ui_request, domain
) -> None:
    """Chrome에 아이콘이 있어도 recorder가 기록하지 않은 도메인은 404다."""
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(ui_request(f"{site_server}/api/site-icons/{domain}"), timeout=2)

    assert exc_info.value.code == 404
    assert json.loads(exc_info.value.read())["error"]["code"] == "not_found"


@pytest.mark.parametrize("referer", [None, "https://evil.example/", "http://127.0.0.1@evil.example/"])
@pytest.mark.parametrize("domain", ["news.example.com", "missing.example.com"])
def test_site_icon_requests_from_other_pages_get_the_same_answer_whether_or_not_it_was_recorded(
    site_server, domain, referer
) -> None:
    """다른 웹페이지가 <img>로 불러 보고 기록된 사이트(news.example.com)와 아닌 사이트를 구별하지
    못해야 한다 — 둘 다 똑같이 캐시되지 않는 404다."""
    headers = {"Referer": referer} if referer else {}
    request = urllib.request.Request(f"{site_server}/api/site-icons/{domain}", headers=headers)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=2)

    assert exc_info.value.code == 404
    assert exc_info.value.headers["Cache-Control"] == "no-store"
    assert json.loads(exc_info.value.read())["error"]["code"] == "not_found"


def test_site_icon_endpoint_is_404_for_a_pre_site_database(tmp_path, ui_request) -> None:
    old_db = tmp_path / "old.db"
    sqlite3.connect(old_db).close()
    _Handler.db_path = old_db
    _Handler.site_icon_store = SiteIconStore([tmp_path / "chrome"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                ui_request(f"http://127.0.0.1:{server.server_port}/api/site-icons/news.example.com"),
                timeout=2,
            )
        assert exc_info.value.code == 404
    finally:
        server.shutdown()


def test_reads_icons_from_every_installed_browser(tmp_path) -> None:
    _write_favicons(tmp_path / "chrome", "Default", [("https://a.example.com/", "from-chrome", 32, 1)])
    _write_favicons(tmp_path / "edge", "Default", [("https://b.example.com/", "from-edge", 32, 1)])
    store = SiteIconStore([tmp_path / "chrome", tmp_path / "edge", tmp_path / "not-installed"])

    assert store.get("a.example.com")[1] == _png("from-chrome")
    assert store.get("b.example.com")[1] == _png("from-edge")


# --- 일시적 실패와 "없음"의 구분, 프로필별 실패, 스트리밍, 정리 ---


def test_a_temporary_read_failure_is_not_remembered_as_no_icon(tmp_path, monkeypatch) -> None:
    """복사가 한 번 실패해도(파일 잠금 등) 곧 복구되면 다음 요청에서 아이콘이 나와야 한다."""
    _write_favicons(tmp_path, "Default", [("https://news.example.com/", "x", 32, 1)])
    store = SiteIconStore([tmp_path])
    real_snapshot = site_icons_module.snapshot_database
    monkeypatch.setattr(site_icons_module, "snapshot_database", lambda s, t: False)

    assert store.get("news.example.com") is None  # 이번엔 못 읽었다

    monkeypatch.setattr(site_icons_module, "snapshot_database", real_snapshot)
    assert store.get("news.example.com")[1] == _png("x")  # 5분 기다리지 않고 바로 복구


def test_no_icon_is_remembered_but_a_profile_without_a_favicons_file_is_not_a_failure(
    tmp_path,
) -> None:
    """Favicons 파일이 없는 프로필(Local State에만 있음)은 실패가 아니라 "여기엔 없음"이다."""
    _write_favicons(tmp_path, "Default", [("https://other.example.com/", "x", 32, 1)])
    (tmp_path / "Profile 1").mkdir()
    (tmp_path / "Local State").write_text(
        json.dumps({"profile": {"info_cache": {"Default": {}, "Profile 1": {}}}}), encoding="utf-8"
    )
    store = SiteIconStore([tmp_path])
    reads = []
    original = store._read_from_browsers
    store._read_from_browsers = lambda d: (reads.append(d), original(d))[1]

    assert store.get("news.example.com") is None
    assert store.get("news.example.com") is None

    assert reads == ["news.example.com"]  # 확인된 "없음"은 기억해서 다시 읽지 않는다


def test_one_broken_profile_does_not_hide_the_icon_in_another_profile(tmp_path) -> None:
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Favicons").write_bytes(b"not a sqlite file")
    _write_favicons(tmp_path, "Profile 1", [("https://news.example.com/", "good", 32, 1)])
    store = SiteIconStore([tmp_path])

    assert store.get("news.example.com")[1] == _png("good")


def test_a_failing_profile_is_skipped_even_when_it_raises_unexpectedly(tmp_path, monkeypatch) -> None:
    _write_favicons(tmp_path, "Default", [("https://news.example.com/", "a", 32, 1)])
    _write_favicons(tmp_path, "Profile 1", [("https://news.example.com/", "b", 32, 9)])
    store = SiteIconStore([tmp_path])
    original = store._query_profile

    def flaky(source, patterns):
        if source.parent.name == "Profile 1":
            raise RuntimeError("boom")
        return original(source, patterns)

    monkeypatch.setattr(store, "_query_profile", flaky)

    assert store.get("news.example.com")[1] == _png("a")


def test_best_candidate_streams_rows_without_building_a_list() -> None:
    """행을 한 줄씩 소비하고(제너레이터), 선호 크기 → 최근 갱신 순으로 고른다."""
    consumed = []

    def rows():
        for row in [(_png("small"), 16, 9), (_png("big-old"), 32, 1), (_png("big-new"), 32, 5)]:
            consumed.append(row[0])
            yield row

    assert _pick_best(rows()) == _png("big-new")
    assert len(consumed) == 3


def test_a_temp_folder_that_cannot_be_removed_is_logged_and_retried(
    tmp_path, monkeypatch, caplog
) -> None:
    _write_favicons(tmp_path, "Default", [("https://news.example.com/", "x", 32, 1)])
    store = SiteIconStore([tmp_path])
    real_remove = site_icons_module.remove_work_dir
    stuck = []

    def fail_once(path):
        if not stuck:
            stuck.append(path)
            return False  # 파일이 잠겨 못 지웠다
        return real_remove(path)

    monkeypatch.setattr(site_icons_module, "remove_work_dir", fail_once)
    with caplog.at_level("WARNING", logger="hub"):
        assert store.get("news.example.com") is not None

    assert any("지우지 못했습니다" in record.message for record in caplog.records)
    assert "news.example.com" not in caplog.text  # 도메인은 로그에 남기지 않는다
    assert store._leftover_dirs == stuck

    real_remove(stuck[0])  # 폴더 정리는 실제로 해 두고
    assert store.get("other.example.com") is None  # 다음 복사 때 남은 폴더를 다시 지워 본다
    assert store._leftover_dirs == []
