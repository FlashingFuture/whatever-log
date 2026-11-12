"""백그라운드 프로세스의 메모리 사용을 줄여 작업 관리자에 낮게 보이게 한다 (Windows).

작업 관리자의 "메모리" 열은 **작업 집합(working set)** 의 전용 부분이다. 파이썬 프로세스는 시작하면서 모듈을 불러오느라 물리 메모리를 20~40MB 잡아 두고,
그 뒤로는 거의 쓰지 않는데도 그대로 들고 있다. `EmptyWorkingSet`은 지금 안 쓰는 페이지를 운영체제에 돌려준다(필요하면 다시 읽어 들인다).

- **효과**(이 PC에서 잰 값, 작업 집합 MB): 기록기 30.6 → 6.4, hub 34.4 → 2.2, 동기화 에이전트 45.5 → 0.5(25초 뒤).
- **한계**: 프로세스가 약속한 메모리(commit, "전용 바이트")는 줄지 않는다. 물리 메모리를 다른 프로그램이 쓸 수 있게 돌려주는 것이라, 메모리가 모자랄 때
  실제로 도움이 되고 평소에는 작업 관리자의 숫자를 낮춘다.
- **쓰는 곳**: 쉬는 시간이 긴 백그라운드 프로세스(기록기·동기화 에이전트·hub·supervisor)만. 사용자가 보고 있는 화면 프로세스(desktop)는 쓰지 않는다 — 다시 읽어 들이느라
  버벅일 수 있다.
"""

import ctypes
import logging
import sys
import threading

logger = logging.getLogger("common.memory")

DEFAULT_INTERVAL_SECONDS = 300.0
#: 시작하고 처음 줄이기까지 기다리는 시간. 시작 직후에는 아직 모듈을 불러오고 DB를 여는 중이라, 그때 줄이면 곧바로 다시 차올라 효과가 없다.
FIRST_TRIM_DELAY_SECONDS = 30.0
_PROCESS_QUERY_AND_SET_QUOTA = 0x0100 | 0x0400  # PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION
_started_lock = threading.Lock()
_started = False


def trim_working_set() -> bool:
    """이 프로세스의 쓰지 않는 물리 메모리를 운영체제에 돌려준다. 했으면 True. Windows가 아니거나 실패해도 예외를 내지 않는다(메모리 정리는 부가 기능이다)."""
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = kernel32.GetCurrentProcess()  # 가짜 핸들(-1)이라 닫지 않는다
        return bool(ctypes.windll.psapi.EmptyWorkingSet(ctypes.c_void_p(handle)))
    except (OSError, AttributeError):
        logger.debug("작업 집합을 줄이지 못했습니다.", exc_info=True)
        return False


def keep_trimmed(interval_seconds: float = DEFAULT_INTERVAL_SECONDS, first_delay_seconds: float = FIRST_TRIM_DELAY_SECONDS) -> bool:
    """이 프로세스의 작업 집합을 first_delay_seconds 뒤에 한 번, 그 뒤 interval_seconds마다 줄이는 백그라운드 스레드를 시작한다.

    프로세스당 한 번만 시작한다(이미 시작했으면 아무것도 하지 않고 False). 스레드는 데몬이라 프로세스가 끝나는 것을 막지 않는다.
    """
    global _started
    with _started_lock:
        if _started or sys.platform != "win32":
            return False
        _started = True
    threading.Thread(target=_loop, args=(interval_seconds, first_delay_seconds), name="trim-working-set", daemon=True).start()
    return True


def _loop(interval_seconds: float, first_delay_seconds: float = 0.0) -> None:
    """first_delay_seconds를 기다린 뒤 줄이고, 그 뒤 interval_seconds마다 반복한다(데몬 스레드의 본체)."""
    stop = threading.Event()
    stop.wait(first_delay_seconds)
    while not stop.is_set():
        trim_working_set()
        stop.wait(interval_seconds)
