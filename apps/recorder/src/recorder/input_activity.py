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
    """사용자가 실제로 자리에 있었는지 판단하는 데 쓸 idle 시간(초)을 반환한다."""
    if sys.platform != "win32":
        raise NotImplementedError(f"{sys.platform}은 아직 지원하지 않습니다.")

    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo 호출에 실패했습니다.")

    last_input_tick = info.dwTime
    current_tick = ctypes.windll.kernel32.GetTickCount()

    # GetTickCount()는 DWORD(32비트)라 약 49.7일마다 0으로 wrap된다. 게다가
    # ctypes는 restype을 지정하지 않으면 반환값을 부호 있는 int로 해석하므로,
    # 부팅 후 ~24.9일(2**31ms)부터 current_tick 자체가 음수로 나온다. info.dwTime은
    # wintypes.DWORD로 선언돼 있어 항상 부호 없는 값이라, 둘을 그냥 빼면 24.9~49.7일
    # 구간에서 진짜 wrap-around가 아닌데도 음수가 나온다. 32비트 모듈러 뺄셈으로
    # 부호 문제와 실제 wrap-around를 한 번에 처리한다.
    elapsed_ms = (current_tick - last_input_tick) & 0xFFFFFFFF
    return elapsed_ms / 1000
