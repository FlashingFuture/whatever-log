"""Windows 시스템 알림(토스트)을 띄운다.

추가 패키지 없이 PowerShell의 WinRT 호출로 띄운다(Windows에 이미 있다). 글자는 명령줄에 끼워 넣지 않고 환경 변수로 넘긴다 — 목표 이름 같은
사용자가 쓴 글에 따옴표나 `$(…)`가 있어도 PowerShell 코드로 해석되지 않는다.

알림에 앱 이름이 `whatever.log`로 보이도록, 처음 띄울 때 현재 사용자의 레지스트리(HKCU)에 앱 식별자(AppUserModelID)를 등록한다. 관리자 권한이
필요 없고 `HKCU\\Software\\Classes\\AppUserModelId\\whatever.log` 한 곳만 건드린다.
"""

import ctypes
import logging
import os
import subprocess
import sys
import winreg
from pathlib import Path

logger = logging.getLogger("notifier.toast")

APP_ID = "whatever.log"
_APP_ID_KEY = rf"Software\Classes\AppUserModelId\{APP_ID}"
_TIMEOUT_SECONDS = 20

_TITLE_VARIABLE = "WHATEVER_LOG_TOAST_TITLE"
_BODY_VARIABLE = "WHATEVER_LOG_TOAST_BODY"

# 글자는 환경 변수에서 읽는다. CreateTextNode를 쓰므로 XML 특수문자를 따로 처리할 필요가 없다.
_SCRIPT = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode($env:{_TITLE_VARIABLE})) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode($env:{_BODY_VARIABLE})) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($toast)
"""


def powershell_path() -> Path:
    """Windows PowerShell의 전체 경로. PATH나 환경 변수에 기대지 않고 시스템 폴더를 운영체제에 묻는다(같은 이름의 가짜 실행 파일을 막는다)."""
    buffer = ctypes.create_unicode_buffer(260)
    ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    return Path(buffer.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def register_app_id() -> None:
    """알림에 보일 앱 이름(whatever.log)을 현재 사용자 레지스트리에 등록한다. 이미 있으면 그대로 둔다."""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _APP_ID_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
        try:
            winreg.QueryValueEx(key, "DisplayName")
        except FileNotFoundError:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_ID)


def show_toast(title: str, body: str) -> bool:
    """알림을 띄운다. 띄웠으면 True, 못 띄웠으면(Windows가 아님, PowerShell 오류, 시간 초과) 이유를 로그에 남기고 False.

    알림은 부가 기능이라 실패해도 예외를 내지 않는다 — 알림이 안 떠도 에이전트는 계속 돌아야 한다.
    """
    if sys.platform != "win32":
        return False
    try:
        register_app_id()
    except OSError:
        logger.warning("알림 앱 이름을 등록하지 못했습니다. 기본 이름으로 알립니다.", exc_info=True)
    environment = {**os.environ, _TITLE_VARIABLE: title, _BODY_VARIABLE: body}
    try:
        completed = subprocess.run(
            [str(powershell_path()), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _SCRIPT],
            env=environment,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("알림을 띄우지 못했습니다.", exc_info=True)
        return False
    if completed.returncode != 0:
        logger.warning("알림을 띄우지 못했습니다(종료 코드 %s): %s", completed.returncode, completed.stderr.strip()[:300])
        return False
    return True
