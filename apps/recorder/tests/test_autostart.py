from unittest.mock import MagicMock, patch

from recorder import autostart


def _mock_key(mock_winreg) -> MagicMock:
    key = MagicMock()
    mock_winreg.OpenKey.return_value.__enter__.return_value = key
    return key


def _mock_created_key(mock_winreg) -> MagicMock:
    key = MagicMock()
    mock_winreg.CreateKeyEx.return_value.__enter__.return_value = key
    return key


def test_enable_sets_the_run_key_to_pythonw_and_supervisor() -> None:
    """등록되는 명령이 콘솔 없는 pythonw.exe로 supervisor를 띄우는 형태여야 한다."""
    with patch("recorder.autostart.winreg") as mock_winreg:
        key = _mock_created_key(mock_winreg)
        autostart.enable()

    _, value_name, _, _, command = mock_winreg.SetValueEx.call_args[0]
    assert mock_winreg.SetValueEx.call_args[0][0] is key
    assert value_name == autostart._VALUE_NAME
    assert "pythonw.exe" in command
    assert "recorder.supervisor" in command


def test_enable_works_when_run_key_does_not_exist_yet() -> None:
    """한 번도 자동시작 앱을 등록한 적 없는 프로필엔 Run 키 자체가 없을 수 있다.
    OpenKey가 아니라 CreateKeyEx를 써야 이 경우에도 등록이 성공한다.
    """
    with patch("recorder.autostart.winreg") as mock_winreg:
        _mock_created_key(mock_winreg)
        autostart.enable()

    mock_winreg.CreateKeyEx.assert_called_once()
    mock_winreg.OpenKey.assert_not_called()


def test_disable_removes_the_run_key_when_present() -> None:
    with patch("recorder.autostart.winreg") as mock_winreg:
        key = _mock_key(mock_winreg)
        autostart.disable()

    mock_winreg.DeleteValue.assert_called_once_with(key, autostart._VALUE_NAME)


def test_disable_is_a_noop_when_not_registered() -> None:
    """등록된 적이 없어도(FileNotFoundError) 조용히 끝나야 한다."""
    with patch("recorder.autostart.winreg") as mock_winreg:
        _mock_key(mock_winreg)
        mock_winreg.DeleteValue.side_effect = FileNotFoundError

        autostart.disable()  # 예외가 나면 테스트 실패


def test_disable_is_a_noop_when_run_key_itself_is_missing() -> None:
    """DeleteValue가 아니라 OpenKey 자체가 FileNotFoundError를 내는 경우(Run 키가
    전혀 없는 프로필)도 조용히 끝나야 한다."""
    with patch("recorder.autostart.winreg") as mock_winreg:
        mock_winreg.OpenKey.side_effect = FileNotFoundError

        autostart.disable()  # 예외가 나면 테스트 실패


def test_is_enabled_true_when_value_exists() -> None:
    with patch("recorder.autostart.winreg") as mock_winreg:
        _mock_key(mock_winreg)
        mock_winreg.QueryValueEx.return_value = ("command", 1)

        assert autostart.is_enabled() is True


def test_is_enabled_false_when_missing() -> None:
    with patch("recorder.autostart.winreg") as mock_winreg:
        _mock_key(mock_winreg)
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError

        assert autostart.is_enabled() is False


def test_is_enabled_false_when_run_key_itself_is_missing() -> None:
    """QueryValueEx가 아니라 OpenKey 자체가 FileNotFoundError를 내는 경우(Run 키가
    전혀 없는 프로필)도 "등록 안 됨"으로 봐야 한다."""
    with patch("recorder.autostart.winreg") as mock_winreg:
        mock_winreg.OpenKey.side_effect = FileNotFoundError

        assert autostart.is_enabled() is False
