from unittest.mock import patch

import pytest

from recorder.input_activity import get_seconds_since_last_input


def test_returns_elapsed_seconds_since_last_input() -> None:
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


def test_returns_zero_when_tick_count_wrapped_around() -> None:
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
        assert get_seconds_since_last_input() == 0.0


def test_raises_when_api_call_fails() -> None:
    with patch("ctypes.windll.user32.GetLastInputInfo", return_value=0):
        with pytest.raises(OSError):
            get_seconds_since_last_input()
