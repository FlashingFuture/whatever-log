"""시스템 전체의 마지막 입력(키보드/마우스) 이후 경과 시간을 가져온다.

Windows의 GetLastInputInfo는 "마지막 입력이 있었던 시각"을 시스템 부팅 이후
경과한 밀리초(tick count)로 준다. 여기서는 그걸 "지금으로부터 몇 초 전인지"로
변환해서 반환한다 — "활동이 있었다/없었다"의 임계값 판단은 호출부(쿼리 시점)의
몫이다 (docs/recorder-sqlite-design.md 참고).
"""

import ctypes
import sys
from ctypes import wintypes


class _LastInputInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def get_seconds_since_last_input() -> float:
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")

    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo 호출에 실패했습니다.")

    last_input_tick = info.dwTime
    current_tick = ctypes.windll.kernel32.GetTickCount()

    # GetTickCount()는 DWORD(32비트)라 약 49.7일마다 0으로 오버플로한다. 그
    # 구간에 걸리면 음수가 나올 수 있는데, 그때는 0으로 처리한다 (활동 있었다고
    # 보는 쪽으로 — "입력 없었음"을 거짓으로 길게 보고하는 것보다 안전).
    elapsed_ms = current_tick - last_input_tick
    if elapsed_ms < 0:
        return 0.0
    return elapsed_ms / 1000
