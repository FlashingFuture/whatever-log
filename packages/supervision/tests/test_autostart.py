from unittest.mock import MagicMock, patch

import pytest
from supervision import autostart


def test_module_command_runs_the_module_with_pythonw() -> None:
    command = autostart.module_command("sync_agent.supervisor", "--interval", "300")

    parsed = _split_windows_command_line(command)
    assert parsed[0].endswith("pythonw.exe") and parsed[1:] == ["-m", "sync_agent.supervisor", "--interval", "300"]


def test_pythonw_is_next_to_the_running_virtualenv_python(monkeypatch, tmp_path) -> None:
    """자동 시작은 지금 가상환경의 pythonw.exe로 띄운다 — 다른 폴더의 파이썬을 등록하면 그 환경의 패키지로 뜬다."""
    scripts = tmp_path / ".venv" / "Scripts"
    monkeypatch.setattr(autostart.sys, "executable", str(scripts / "python.exe"))

    assert autostart.pythonw_path() == scripts / "pythonw.exe"
    assert _split_windows_command_line(autostart.module_command("recorder.supervisor"))[0] == str(scripts / "pythonw.exe")


def test_arguments_with_spaces_and_quotes_stay_single_arguments() -> None:
    """공백이 든 경로를 그냥 이어 붙이면 인자가 둘로 쪼개져 자동 시작 때 인자 오류로 죽는다."""
    command = autostart.module_command("recorder.supervisor", "--db-path", r"C:\My Logs\state.db", 'a"b')

    parsed = _split_windows_command_line(command)
    assert parsed[-3:] == ["--db-path", r"C:\My Logs\state.db", 'a"b']


def _split_windows_command_line(command: str) -> list[str]:
    """윈도우가 명령줄을 인자로 나누는 방식(CommandLineToArgvW) 그대로 나눈다."""
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    count = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def test_registered_command_reads_the_value_or_none() -> None:
    with patch("supervision.autostart.winreg") as winreg:
        winreg.OpenKey.return_value.__enter__.return_value = MagicMock()
        winreg.QueryValueEx.return_value = ("the command", 1)
        assert autostart.registered_command("MyValue") == "the command"
        winreg.QueryValueEx.side_effect = FileNotFoundError
        assert autostart.registered_command("MyValue") is None


def test_enable_registers_the_given_name_and_command() -> None:
    with patch("supervision.autostart.winreg") as winreg, patch("supervision.autostart.Path.exists", return_value=True):
        key = MagicMock()
        winreg.CreateKeyEx.return_value.__enter__.return_value = key
        autostart.enable("MyValue", "the command")

    winreg.SetValueEx.assert_called_once_with(key, "MyValue", 0, winreg.REG_SZ, "the command")


def test_enable_refuses_when_pythonw_is_missing() -> None:
    with patch("supervision.autostart.winreg") as winreg, patch("supervision.autostart.Path.exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            autostart.enable("MyValue", "x")

    winreg.CreateKeyEx.assert_not_called()


def test_disable_and_status_use_the_given_name() -> None:
    with patch("supervision.autostart.winreg") as winreg:
        key = MagicMock()
        winreg.OpenKey.return_value.__enter__.return_value = key

        autostart.disable("MyValue")
        winreg.QueryValueEx.return_value = ("c", 1)
        assert autostart.is_enabled("MyValue") is True

    winreg.DeleteValue.assert_called_once_with(key, "MyValue")
    winreg.QueryValueEx.assert_called_once_with(key, "MyValue")


# --- 릴리스 번들의 실행 파일 이름 ---


@pytest.mark.parametrize(
    ("running", "expected"),
    [
        (r"C:\app\runtime\whatever-log-cli.exe", r"C:\app\runtime\whatever-log.exe"),  # 관리 명령(콘솔)으로 실행 중이면 같은 폴더의 콘솔 없는 쪽
        (r"C:\app\runtime\whatever-log.exe", r"C:\app\runtime\whatever-log.exe"),  # 이미 콘솔 없는 쪽이면 자기 자신
        (r"C:\dev\.venv\Scripts\python.exe", r"C:\dev\.venv\Scripts\pythonw.exe"),  # 개발 환경은 pythonw.exe
        (r"C:\dev\.venv\Scripts\pythonw.exe", r"C:\dev\.venv\Scripts\pythonw.exe"),
    ],
)
def test_the_windowless_executable_depends_on_whether_this_is_a_bundle(running, expected) -> None:
    with patch("supervision.autostart.sys.executable", running):
        assert str(autostart.pythonw_path()).lower() == expected.lower()


def test_a_dev_virtualenv_is_never_mistaken_for_a_bundle_just_because_whatever_log_exe_exists(tmp_path) -> None:
    """가상환경의 Scripts 폴더에도 whatever-log.exe(명령 실행기)가 있다 — 파일이 있는지로 가리면 개발 환경에서 그것을 고른다(창을 소유하지 못하는 실행기)."""
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "whatever-log.exe").write_bytes(b"launcher")

    with patch("supervision.autostart.sys.executable", str(scripts / "python.exe")):
        assert autostart.pythonw_path().name == "pythonw.exe"


def test_the_autostart_command_in_a_bundle_runs_the_renamed_executable() -> None:
    with patch("supervision.autostart.sys.executable", r"C:\Users\이름 있는\app\runtime\whatever-log-cli.exe"):
        command = autostart.module_command("recorder.supervisor")

    parsed = _split_windows_command_line(command)
    assert parsed[0].endswith(r"runtime\whatever-log.exe") and parsed[1:] == ["-m", "recorder.supervisor"]
