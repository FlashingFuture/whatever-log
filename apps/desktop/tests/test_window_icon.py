import ctypes
import os
import struct
from unittest.mock import MagicMock, patch

from desktop import window_icon


def test_the_shipped_icon_holds_every_size_the_taskbar_and_title_bar_need() -> None:
    data = window_icon.ICON_PATH.read_bytes()

    reserved, kind, count = struct.unpack_from("<HHH", data)
    sizes = {(data[6 + 16 * i] or 256) for i in range(count)}  # 폭 칸: 0은 256을 뜻한다
    assert (reserved, kind) == (0, 1)
    assert sizes == {16, 24, 32, 48, 64, 128, 256}


def test_no_icon_is_applied_when_the_file_is_missing(tmp_path) -> None:
    assert window_icon.apply_window_icon("whatever.log", tmp_path / "missing.ico") is False


def test_no_icon_is_applied_when_this_process_has_no_such_window() -> None:
    assert window_icon.apply_window_icon("whatever.log - no such window 4f9a1c") is False


# --- AppUserModelID: 실제 API를 부르지 않고 각 경로를 검증한다(테스트 프로세스의 ID를 바꾸지 않는다) ---


def test_the_app_user_model_id_succeeds_when_the_api_returns_zero() -> None:
    api = MagicMock(return_value=0)
    with patch.object(window_icon.sys, "platform", "win32"), patch.object(window_icon, "ctypes") as fake:
        fake.windll.shell32.SetCurrentProcessExplicitAppUserModelID = api
        assert window_icon.set_app_user_model_id("Test.Id") is True

    api.assert_called_once_with("Test.Id")


def test_the_app_user_model_id_reports_a_failing_hresult() -> None:
    with patch.object(window_icon.sys, "platform", "win32"), patch.object(window_icon, "ctypes") as fake:
        fake.windll.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0x80070057
        assert window_icon.set_app_user_model_id() is False


def test_the_app_user_model_id_survives_an_api_that_cannot_be_called() -> None:
    with patch.object(window_icon.sys, "platform", "win32"), patch.object(window_icon, "ctypes") as fake:
        fake.windll.shell32.SetCurrentProcessExplicitAppUserModelID.side_effect = OSError
        assert window_icon.set_app_user_model_id() is False


def test_the_app_user_model_id_is_not_set_off_windows() -> None:
    with patch.object(window_icon.sys, "platform", "linux"):
        assert window_icon.set_app_user_model_id() is False


# --- 창 찾기: 같은 제목의 다른 프로세스 창에는 손대지 않는다 ---


def test_a_window_with_the_same_title_in_another_process_is_not_ours() -> None:
    """같은 제목의 남의 창에 아이콘을 붙이고 우리 창은 기본 아이콘으로 남지 않게, 소유 프로세스까지 본다."""
    user32 = ctypes.windll.user32
    other = _make_foreign_window("whatever.log")
    try:
        assert window_icon.find_own_window("whatever.log") is None  # 이 프로세스에는 그 제목의 창이 없다
        assert os.getpid() != other.pid
    finally:
        other.terminate()
        other.wait()
    assert user32  # (창 조회 API가 이 환경에서 쓸 수 있음)


def _make_foreign_window(title: str):
    """다른 프로세스에서 제목이 title인 창을 하나 연다(숨기지 않고 잠깐 둔다)."""
    import subprocess
    import sys
    import time

    code = (
        "import ctypes,time;"
        "u=ctypes.windll.user32;"
        f"h=u.CreateWindowExW(0,'Static',{title!r},0x10000000,0,0,50,50,0,0,0,0);"
        "time.sleep(30)"
    )
    process = subprocess.Popen([sys.executable, "-c", code])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if ctypes.windll.user32.FindWindowW(None, title):
            break
        time.sleep(0.05)
    return process


def test_a_window_this_process_owns_is_found_by_title() -> None:
    user32 = ctypes.windll.user32
    user32.CreateWindowExW.restype = ctypes.c_void_p
    title = "whatever.log own window 7c1e"
    hwnd = user32.CreateWindowExW(0, "Static", title, 0x10000000, 0, 0, 50, 50, None, None, None, None)
    try:
        assert hwnd
        assert window_icon.find_own_window(title) == hwnd
    finally:
        user32.DestroyWindow(ctypes.c_void_p(hwnd))
