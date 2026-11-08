from unittest.mock import MagicMock, patch

import pytest
from supervision import autostart


def test_module_command_runs_the_module_with_pythonw_and_quotes_the_path() -> None:
    command = autostart.module_command("sync_agent.supervisor", "--interval", "300")

    assert command.startswith('"') and 'pythonw.exe" -m sync_agent.supervisor --interval 300' in command


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
