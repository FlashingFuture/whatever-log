import struct

from desktop import window_icon


def test_the_shipped_icon_holds_every_size_the_taskbar_and_title_bar_need() -> None:
    data = window_icon.ICON_PATH.read_bytes()

    reserved, kind, count = struct.unpack_from("<HHH", data)
    sizes = {(data[6 + 16 * i] or 256) for i in range(count)}  # 폭 칸: 0은 256을 뜻한다
    assert (reserved, kind) == (0, 1)
    assert sizes == {16, 24, 32, 48, 64, 128, 256}


def test_no_icon_is_applied_when_the_file_is_missing(tmp_path) -> None:
    assert window_icon.apply_window_icon("whatever.log", tmp_path / "missing.ico") is False


def test_no_icon_is_applied_when_there_is_no_such_window() -> None:
    assert window_icon.apply_window_icon("whatever.log - no such window 4f9a1c") is False


def test_the_app_user_model_id_is_set_without_error() -> None:
    assert window_icon.set_app_user_model_id("WhateverLog.Test") is True
