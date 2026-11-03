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


def test_lock_for_returns_the_same_lock_per_key() -> None:
    cache = ImageMemoryCache()

    assert cache.lock_for("a") is cache.lock_for("a")
    assert cache.lock_for("a") is not cache.lock_for("b")
