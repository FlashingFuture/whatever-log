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
