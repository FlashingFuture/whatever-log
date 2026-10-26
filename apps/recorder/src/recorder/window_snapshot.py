"""현재 떠 있는 창들의 소유 프로세스 이름을 가져온다.

Windows의 "창이 몇 초간 떠 있었는지"를 알려주는 공개 API나 영속 카운터는
따로 없다 (Settings의 스크린 타임은 비공개 내부 데이터). 그래서 지금은 폴링
방식으로 직접 센다. 더 효율적인 방법(예: SetWinEventHook으로 포커스/창 변경
이벤트를 구독)으로 바꾸고 싶어지면 이 모듈만 교체하면 된다 — 호출부는 아래
두 함수의 시그니처만 알면 되도록 분리해 뒀다.

두 함수는 서로 독립적이다. get_windowed_process_names()는 foreground도
포함한 "창이 있는 프로세스 전체"이고, foreground를 빼지 않는다 — 어느 게
foreground인지는 get_foreground_process_name()으로 별도로 알아내서 쓴다.

"주요 프로세스"는 제목이 있는 보이는 최상위 창을 가진 프로세스로 정의한다.
svchost 같은 순수 백그라운드 서비스는 창이 없어서 자연히 빠진다.
"""

import ctypes
import sys
from ctypes import wintypes

import psutil

if sys.platform == "win32":
    # restype을 지정하지 않으면 ctypes가 반환값을 부호 있는 32비트 int로 해석한다.
    # HWND 값이 실제로 2**31을 넘는 일은 거의 없어서 지금은 문제가 안 되지만,
    # GetTickCount()에서 바로 이 문제로 실제 버그가 났던 적이 있어(input_activity.py)
    # 같은 함정을 방어적으로 막아둔다.
    ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND


def _pid_to_process_name(pid: int) -> str | None:
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        # NoSuchProcess뿐 아니라 AccessDenied(관리자 권한 프로세스 등)도 여기서
        # 걸러야 한다 — 안 그러면 foreground 조회에서는 예외가 기록 루프까지
        # 전파되고, EnumWindows 콜백 안에서는 ctypes가 콜백을 중단시켜서 그
        # 틱의 창 목록이 중간에 잘린다.
        return None


def _hwnd_to_process_name(hwnd: int) -> str | None:
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    return _pid_to_process_name(pid.value)


def get_foreground_process_name() -> str | None:
    """현재 활성(포커스된) 창을 소유한 프로세스 이름."""
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None
    return _hwnd_to_process_name(hwnd)


def get_windowed_process_names() -> set[str]:
    """보이는 최상위 창을 가진 프로세스 이름 전체 (foreground도 포함됨)."""
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")

    user32 = ctypes.windll.user32
    names: set[str] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_handler(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True

        name = _hwnd_to_process_name(hwnd)
        if name is not None:
            names.add(name)
        return True

    user32.EnumWindows(_enum_handler, 0)
    return names
