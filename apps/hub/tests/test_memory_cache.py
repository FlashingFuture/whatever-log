import threading
import time

import pytest

from hub.memory_cache import ImageMemoryCache


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_evicts_the_least_recently_used_entry() -> None:
    cache = ImageMemoryCache(max_entries=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    assert cache.get("a") == b"1"  # a를 쓰면 b가 가장 오래 안 쓴 것이 된다

    cache.put("c", b"3")

    assert cache.get("b") is None
    assert cache.get("a") == b"1" and cache.get("c") == b"3"


def test_entries_expire_only_when_a_ttl_is_given() -> None:
    clock = _Clock()
    with_ttl = ImageMemoryCache(ttl_seconds=60, clock=clock)
    forever = ImageMemoryCache(clock=clock)
    with_ttl.put("k", b"x")
    forever.put("k", b"x")

    clock.now += 59
    assert with_ttl.get("k") == b"x"
    clock.now += 2

    assert with_ttl.get("k") is None
    assert forever.get("k") == b"x"


def test_a_miss_is_remembered_until_it_expires_and_a_hit_clears_it() -> None:
    clock = _Clock()
    cache = ImageMemoryCache(missing_ttl_seconds=30, clock=clock)

    assert not cache.is_missing("k")
    cache.mark_missing("k")
    assert cache.is_missing("k")
    clock.now += 31
    assert not cache.is_missing("k")

    cache.mark_missing("k")
    cache.put("k", b"x")
    assert not cache.is_missing("k")


def _race(cache: ImageMemoryCache, key: str, load, count: int = 6) -> list:
    results: list = []
    threads = [
        threading.Thread(target=lambda: results.append(cache.get_or_load(key, load)))
        for _ in range(count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_get_or_load_loads_once_for_concurrent_hits() -> None:
    cache = ImageMemoryCache()
    calls = []

    def load():
        calls.append(1)
        time.sleep(0.15)
        return b"img"

    assert _race(cache, "k", load) == [b"img"] * 6
    assert len(calls) == 1
    assert cache.get("k") == b"img"


def test_get_or_load_loads_once_for_concurrent_failures() -> None:
    """앞선 호출이 실패해 "없음"을 기록한 뒤, 잠금을 기다리던 호출이 같은 조회를 되풀이하지 않는다."""
    cache = ImageMemoryCache()
    calls = []

    def load():
        calls.append(1)
        time.sleep(0.15)
        return None

    assert _race(cache, "k", load) == [None] * 6
    assert len(calls) == 1
    assert cache.is_missing("k")


def test_get_or_load_does_not_remember_anything_when_load_raises() -> None:
    cache = ImageMemoryCache()

    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        cache.get_or_load("k", boom)

    assert not cache.is_missing("k") and cache.get("k") is None
    assert cache.get_or_load("k", lambda: b"ok") == b"ok"  # 잠금이 풀려 다시 시도할 수 있다


def test_key_locks_are_dropped_when_nobody_is_using_them() -> None:
    """키가 계속 늘어도(도메인마다 하나) 잠금 목록이 같이 늘면 안 된다."""
    cache = ImageMemoryCache(max_entries=2)

    for index in range(50):
        cache.get_or_load(f"key{index}", lambda: b"x")
        cache.get_or_load(f"missing{index}", lambda: None)

    assert cache._locks == {}
