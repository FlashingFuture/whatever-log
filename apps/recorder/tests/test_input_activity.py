from unittest.mock import patch

import pytest

from recorder.input_activity import get_seconds_since_last_input


def test_returns_elapsed_seconds_since_last_input() -> None:
    """두 tick 값의 차이가 밀리초 단위에서 초 단위로 정확히 환산돼야 한다."""

    def fake_get_last_input_info(info_ref):
        info_ref._obj.dwTime = 7_000
        return 1

    with (
        patch(
            "ctypes.windll.user32.GetLastInputInfo",
            side_effect=fake_get_last_input_info,
        ),
        patch("ctypes.windll.kernel32.GetTickCount", return_value=10_000),
    ):
        assert get_seconds_since_last_input() == 3.0


def test_handles_tick_count_wrapped_around() -> None:
    """실제 wrap-around(~49.7일) 구간에서도 모듈러 뺄셈으로 실제 경과 시간이 나와야 한다."""

    def fake_get_last_input_info(info_ref):
        info_ref._obj.dwTime = 4_000_000_000  # GetTickCount가 막 wrap되기 전 값
        return 1

    with (
        patch(
            "ctypes.windll.user32.GetLastInputInfo",
            side_effect=fake_get_last_input_info,
        ),
        patch("ctypes.windll.kernel32.GetTickCount", return_value=100),  # wrap 직후
    ):
        # (2**32 - 4_000_000_000 + 100)ms을 초로 환산한 값
        assert get_seconds_since_last_input() == pytest.approx(294_967.396)


def test_handles_signed_tick_count_after_24_days_uptime() -> None:
    """ctypes가 restype 없이 GetTickCount를 부호 있는 int로 돌려주는 구간(부팅 후
    ~24.9일 이후)에서도 실제 wrap-around가 아닌 이상 올바른 경과 시간이 나와야 한다.
    """

    def fake_get_last_input_info(info_ref):
        info_ref._obj.dwTime = 3_294_962_296
        return 1

    with (
        patch(
            "ctypes.windll.user32.GetLastInputInfo",
            side_effect=fake_get_last_input_info,
        ),
        # ctypes 기본 restype(c_int)은 실제 unsigned 값 3_294_967_296을
        # 음수로 돌려준다.
        patch("ctypes.windll.kernel32.GetTickCount", return_value=-1_000_000_000),
    ):
        assert get_seconds_since_last_input() == 5.0


def test_raises_when_api_call_fails() -> None:
    """GetLastInputInfo가 실패(0 반환)하면 조용히 넘기지 않고 OSError를 내야 한다."""
    with patch("ctypes.windll.user32.GetLastInputInfo", return_value=0):
        with pytest.raises(OSError):
            get_seconds_since_last_input()
