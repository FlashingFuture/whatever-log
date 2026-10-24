import pytest

from recorder.lock import acquire_lock


def test_acquire_lock_succeeds_when_free(tmp_path) -> None:
    """아무도 안 잡고 있는 lock은 바로 성공해야 한다."""
    lock = acquire_lock(tmp_path / "test.lock")
    assert lock.is_locked
    lock.release()


def test_acquire_lock_fails_when_already_held(tmp_path) -> None:
    """이미 다른 쪽이 잡고 있으면 기다리지 않고 바로 RuntimeError여야 한다(중복 실행 방지)."""
    lock_path = tmp_path / "test.lock"
    first = acquire_lock(lock_path)

    try:
        with pytest.raises(RuntimeError):
            acquire_lock(lock_path)
    finally:
        first.release()


def test_lock_is_released_and_reusable(tmp_path) -> None:
    """release() 이후에는 같은 경로로 다시 잡을 수 있어야 한다."""
    lock_path = tmp_path / "test.lock"
    first = acquire_lock(lock_path)
    first.release()

    second = acquire_lock(lock_path)
    second.release()
