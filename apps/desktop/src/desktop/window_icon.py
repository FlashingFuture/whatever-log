"""창과 작업표시줄에 python 기본 아이콘 대신 앱 아이콘을 쓰게 한다 (Windows).

창은 pythonw.exe 프로세스가 연 것이라 아무것도 하지 않으면 작업표시줄에 파이썬 아이콘이 나온다. 두 가지를 한다:

1. 프로세스에 고유한 AppUserModelID를 준다 — 작업표시줄이 이 창을 python.exe의 창들과 묶지 않고 별개의 앱으로 다룬다.
2. 창에 아이콘을 직접 붙인다(WM_SETICON) — 제목 표시줄과 작업표시줄 단추가 이 아이콘을 쓴다.

실패해도(아이콘 파일이 없거나 윈도우가 아닌 환경) 앱은 그대로 뜬다 — 아이콘은 겉모습일 뿐이라 로그만 남긴다.
"""

import ctypes
import logging
import sys
from pathlib import Path

logger = logging.getLogger("desktop")

APP_USER_MODEL_ID = "WhateverLog.Desktop"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"

_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_SM_CXICON, _SM_CYICON, _SM_CXSMICON, _SM_CYSMICON = 11, 12, 49, 50


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """작업표시줄이 이 프로세스를 python.exe와 따로 다루게 한다. 창을 만들기 전에 불러야 한다. 성공하면 True."""
    if sys.platform != "win32":
        return False
    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError):
        logger.warning("AppUserModelID를 설정하지 못했습니다.")
        return False
    return result == 0


def apply_window_icon(title: str, icon_path: Path = ICON_PATH) -> bool:
    """제목이 title인 창에 아이콘을 붙인다. 창이 아직 없거나 아이콘을 읽지 못하면 False(앱은 계속 뜬다).

    큰 아이콘(작업표시줄·Alt+Tab)과 작은 아이콘(제목 표시줄)을 각자 알맞은 크기로 읽는다 — .ico에 여러 크기가 있으므로
    윈도우가 그 크기에 가장 가까운 그림을 고른다(작은 크기에는 단순한 mark가 쓰인다).
    """
    if sys.platform != "win32" or not icon_path.is_file():
        return False
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.LoadImageW.restype = ctypes.c_void_p
    applied = False
    for kind, width_metric, height_metric in (
        (_ICON_BIG, _SM_CXICON, _SM_CYICON),
        (_ICON_SMALL, _SM_CXSMICON, _SM_CYSMICON),
    ):
        handle = user32.LoadImageW(
            None,
            str(icon_path),
            _IMAGE_ICON,
            user32.GetSystemMetrics(width_metric),
            user32.GetSystemMetrics(height_metric),
            _LR_LOADFROMFILE,
        )
        if handle:
            user32.SendMessageW(ctypes.c_void_p(hwnd), _WM_SETICON, kind, ctypes.c_void_p(handle))
            applied = True
    return applied
