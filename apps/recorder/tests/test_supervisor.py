import sys
from unittest.mock import MagicMock, patch

from recorder import supervisor


def test_stops_after_clean_exit(monkeypatch) -> None:
    """정상 종료(exit 0)면 재시작하지 않고 끝나야 한다."""
    monkeypatch.setattr(sys, "argv", ["supervisor", "--interval", "5"])

    with (
        patch("recorder.supervisor.subprocess.run") as mock_run,
        patch("recorder.supervisor.time.sleep") as mock_sleep,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        supervisor.main()

    mock_run.assert_called_once()
    mock_sleep.assert_not_called()


def test_restarts_after_crash_then_stops_on_clean_exit(monkeypatch) -> None:
    """비정상 종료 후 재시작하고, 그다음 정상 종료되면 거기서 멈춰야 한다."""
    monkeypatch.setattr(sys, "argv", ["supervisor"])

    with (
        patch("recorder.supervisor.subprocess.run") as mock_run,
        patch("recorder.supervisor.time.sleep") as mock_sleep,
    ):
        mock_run.side_effect = [MagicMock(returncode=1), MagicMock(returncode=0)]
        supervisor.main()

    assert mock_run.call_count == 2
    mock_sleep.assert_called_once_with(supervisor.RESTART_DELAY_SECONDS)


def test_passes_through_cli_args(monkeypatch) -> None:
    """supervisor 자신에게 들어온 인자를 그대로 recorder 자식 프로세스에 넘겨야 한다."""
    monkeypatch.setattr(sys, "argv", ["supervisor", "--interval", "30", "--db-path", "x.db"])

    with patch("recorder.supervisor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        supervisor.main()

    called_args = mock_run.call_args[0][0]
    assert called_args == [sys.executable, "-m", "recorder", "--interval", "30", "--db-path", "x.db"]
