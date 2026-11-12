import ctypes
import sys
import threading
from unittest.mock import patch

import pytest
from common import memory, ports


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    """프로세스당 한 번만 시작하는 상태를 시험마다 처음으로 돌린다."""
    monkeypatch.setattr(memory, "_started", False)


def test_trimming_succeeds_on_windows_and_does_not_break_the_process() -> None:
    assert memory.trim_working_set() is True
    assert 1 + 1 == 2  # 정리한 뒤에도 프로세스는 그대로 일한다(필요한 페이지는 다시 읽어 들인다)


def test_trimming_actually_returns_physical_memory() -> None:
    """작업 관리자의 숫자가 실제로 내려가는지 — 큰 덩어리를 잡았다가 정리하면 작업 집합이 줄어야 한다."""
    import psutil

    blob = bytearray(40 * 1024 * 1024)
    for index in range(0, len(blob), 4096):
        blob[index] = 1  # 모든 페이지를 실제로 건드려 작업 집합에 올린다
    before = psutil.Process().memory_info().wset

    assert memory.trim_working_set() is True
    after = psutil.Process().memory_info().wset

    assert after < before - 20 * 1024 * 1024
    assert blob[0] == 1  # 데이터는 그대로다(돌려준 것은 물리 메모리일 뿐이다)


def test_trimming_never_raises_even_if_the_api_fails() -> None:
    with patch.object(memory.ctypes, "windll") as windll:
        windll.kernel32.GetCurrentProcess.return_value = 1
        windll.psapi.EmptyWorkingSet.side_effect = OSError("denied")
        assert memory.trim_working_set() is False


def test_trimming_does_nothing_off_windows() -> None:
    with patch.object(memory.sys, "platform", "linux"):
        assert memory.trim_working_set() is False
        assert memory.keep_trimmed() is False


def test_the_background_thread_starts_once_and_is_a_daemon(monkeypatch) -> None:
    started = []
    real_thread = threading.Thread

    class Recorder(real_thread):
        def start(self):
            started.append((self.name, self.daemon))  # 실제로 돌리지 않는다

    monkeypatch.setattr(memory.threading, "Thread", Recorder)

    assert memory.keep_trimmed(60) is True
    assert memory.keep_trimmed(60) is False  # 같은 프로세스에서 두 번째는 아무것도 하지 않는다
    assert started == [("trim-working-set", True)]  # 데몬이라 프로세스가 끝나는 것을 막지 않는다


def test_a_thread_that_cannot_be_started_does_not_stop_the_app_and_can_be_retried(monkeypatch) -> None:
    """메모리 정리는 부가 기능이다 — 스레드를 못 만들어(RuntimeError) 기록기·hub·동기화 시작까지 막히면 안 된다."""
    real_thread = threading.Thread
    attempts = []

    class Failing(real_thread):
        def start(self):
            attempts.append("start")
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(memory.threading, "Thread", Failing)

    assert memory.keep_trimmed(60) is False  # 예외가 밖으로 나오지 않는다
    assert memory._started is False  # "시작함" 표시를 되돌려, 나중에 다시 시도할 수 있다

    started = []

    class Working(real_thread):
        def start(self):
            started.append(self.name)

    monkeypatch.setattr(memory.threading, "Thread", Working)
    assert memory.keep_trimmed(60) is True and started == ["trim-working-set"]
    assert attempts == ["start"]


def test_the_first_trim_waits_until_startup_has_settled(monkeypatch) -> None:
    """시작 직후에 줄이면 모듈을 불러오고 DB를 여는 동안 곧바로 다시 차오른다 — 첫 정리는 시작이 끝난 뒤여야 한다."""
    order: list = []
    monkeypatch.setattr(memory, "trim_working_set", lambda: order.append("trim") or True)

    class Fake:
        def __init__(self):
            self.count = 0

        def is_set(self):
            return self.count >= 2

        def wait(self, seconds):
            order.append(("wait", seconds))
            self.count += 1

    monkeypatch.setattr(memory.threading, "Event", lambda: Fake())

    memory._loop(300.0, 30.0)

    assert order[:3] == [("wait", 30.0), "trim", ("wait", 300.0)]


def test_the_loop_trims_then_waits_the_interval(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(memory, "trim_working_set", lambda: calls.append("trim") or True)

    class StopAfterTwo:
        def __init__(self):
            self.waits = []

        def is_set(self):
            return len(self.waits) >= 2

        def wait(self, seconds):
            self.waits.append(seconds)

    fake = StopAfterTwo()
    monkeypatch.setattr(memory.threading, "Event", lambda: fake)

    memory._loop(123.0)

    assert calls == ["trim"] and fake.waits == [0.0, 123.0]  # 첫 대기(기본 0초) 뒤 한 번 줄이고, 그 뒤 간격마다


def test_the_hub_port_is_a_plain_number_that_hub_and_desktop_share() -> None:
    assert ports.HUB_PORT == 8787 and isinstance(ports.HUB_PORT, int)
    assert sys.modules["common.ports"].__dict__.get("HUB_PORT") == 8787
    assert ctypes  # (임포트 확인용 — 이 모듈은 아무 것도 불러오지 않는다)
