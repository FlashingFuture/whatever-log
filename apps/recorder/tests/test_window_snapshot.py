from unittest.mock import MagicMock, patch

from recorder.window_snapshot import (
    get_foreground_process_name,
    get_windowed_process_names,
)


def test_get_foreground_process_name_resolves_pid_to_name() -> None:
    def fake_get_pid(_hwnd, pid_ref):
        pid_ref._obj.value = 1234
        return 1

    with (
        patch("ctypes.windll.user32.GetForegroundWindow", return_value=42),
        patch(
            "ctypes.windll.user32.GetWindowThreadProcessId",
            side_effect=fake_get_pid,
        ),
        patch("recorder.window_snapshot.psutil.Process") as mock_process,
    ):
        mock_process.return_value.name.return_value = "Code.exe"

        assert get_foreground_process_name() == "Code.exe"
        mock_process.assert_called_once_with(1234)


def test_get_foreground_process_name_returns_none_when_no_window() -> None:
    with patch("ctypes.windll.user32.GetForegroundWindow", return_value=0):
        assert get_foreground_process_name() is None


def test_get_windowed_process_names_filters_invisible_and_titleless_windows() -> None:
    # hwnd -> (visible, title_length, pid)
    windows = {
        1: (True, 5, 100),  # 보임 + 제목 있음 -> 포함
        2: (False, 5, 200),  # 안 보임 -> 제외
        3: (True, 0, 300),  # 제목 없음 -> 제외
    }
    pid_to_name = {100: "chrome.exe"}

    def fake_enum_windows(callback, lparam):
        for hwnd in windows:
            callback(hwnd, lparam)
        return True

    def fake_is_visible(hwnd):
        return windows[hwnd][0]

    def fake_title_length(hwnd):
        return windows[hwnd][1]

    def fake_get_pid(hwnd, pid_ref):
        pid_ref._obj.value = windows[hwnd][2]
        return 1

    def fake_process(pid):
        proc = MagicMock()
        proc.name.return_value = pid_to_name[pid]
        return proc

    with (
        patch("ctypes.windll.user32.EnumWindows", side_effect=fake_enum_windows),
        patch("ctypes.windll.user32.IsWindowVisible", side_effect=fake_is_visible),
        patch(
            "ctypes.windll.user32.GetWindowTextLengthW",
            side_effect=fake_title_length,
        ),
        patch(
            "ctypes.windll.user32.GetWindowThreadProcessId",
            side_effect=fake_get_pid,
        ),
        patch("recorder.window_snapshot.psutil.Process", side_effect=fake_process),
    ):
        names = get_windowed_process_names()

    assert names == {"chrome.exe"}
