"""현재 활성(foreground) 창을 소유한 프로세스 이름을 가져온다.

Windows의 "활성 창이 몇 초간 떠 있었는지"를 알려주는 공개 API나 영속 카운터는
따로 없다 (Settings의 스크린 타임은 비공개 내부 데이터). 그래서 지금은 폴링
방식으로 직접 센다. 더 효율적인 방법(예: SetWinEventHook으로 포커스 변경
이벤트를 구독)으로 바꾸고 싶어지면 이 함수만 교체하면 된다 — 호출부는
get_active_process_name()의 시그니처만 알면 되도록 분리해 뒀다.
"""

import ctypes
import sys

import psutil


def get_active_process_name() -> str | None:
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")

    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None

    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None

    try:
        return psutil.Process(pid.value).name()
    except psutil.NoSuchProcess:
        return None
