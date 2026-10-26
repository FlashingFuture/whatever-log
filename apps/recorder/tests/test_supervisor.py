import sys
from unittest.mock import MagicMock, patch

import pytest

from recorder import supervisor


@pytest.fixture(autouse=True)
def _use_temp_log_path(tmp_path, monkeypatch):
    """실제 apps/recorder/supervisor.log를 건드리지 않고 임시 파일로 로깅하게 한다."""
    monkeypatch.setattr(supervisor, "DEFAULT_LOG_PATH", tmp_path / "supervisor.log")
    yield
    supervisor.logger.handlers.clear()


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


def test_stops_without_restarting_when_already_running(monkeypatch) -> None:
    """다른 recorder가 이미 lock을 잡고 있는 상황(EXIT_ALREADY_RUNNING)은 크래시가
    아니므로 재시작하면 안 된다 — 안 그러면 5초마다 영원히 재시도하며 로그만 쌓인다.
    """
    monkeypatch.setattr(sys, "argv", ["supervisor"])

    with (
        patch("recorder.supervisor.subprocess.run") as mock_run,
        patch("recorder.supervisor.time.sleep") as mock_sleep,
    ):
        mock_run.return_value = MagicMock(returncode=supervisor.EXIT_ALREADY_RUNNING)
        supervisor.main()

    mock_run.assert_called_once()
    mock_sleep.assert_not_called()


def test_stops_without_restarting_on_argument_error(monkeypatch) -> None:
    """인자 오류(EXIT_ARGUMENT_ERROR)는 같은 인자로 재시도해도 똑같이 실패하므로
    재시작하면 안 되고, "이미 실행 중"이 아니라 인자 오류로 로그에 남아야 한다.
    """
    monkeypatch.setattr(sys, "argv", ["supervisor", "--interval", "0"])

    with (
        patch("recorder.supervisor.subprocess.run") as mock_run,
        patch("recorder.supervisor.time.sleep") as mock_sleep,
    ):
        mock_run.return_value = MagicMock(returncode=supervisor.EXIT_ARGUMENT_ERROR)
        supervisor.main()

    mock_run.assert_called_once()
    mock_sleep.assert_not_called()

    for handler in supervisor.logger.handlers:
        handler.flush()
    log_content = supervisor.DEFAULT_LOG_PATH.read_text(encoding="utf-8")
    assert "인자가 잘못되었습니다" in log_content
    assert "이미 실행 중" not in log_content


def test_exit_codes_do_not_collide() -> None:
    """argparse 인자 오류와 중복 실행이 같은 종료 코드를 쓰면 supervisor가 둘을 구분하지 못한다."""
    assert supervisor.EXIT_ARGUMENT_ERROR != supervisor.EXIT_ALREADY_RUNNING


def test_passes_through_cli_args(monkeypatch) -> None:
    """supervisor 자신에게 들어온 인자를 그대로 recorder 자식 프로세스에 넘겨야 한다."""
    monkeypatch.setattr(sys, "argv", ["supervisor", "--interval", "30", "--db-path", "x.db"])

    with patch("recorder.supervisor.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        supervisor.main()

    called_args = mock_run.call_args[0][0]
    assert called_args == [sys.executable, "-m", "recorder", "--interval", "30", "--db-path", "x.db"]


def test_restart_decision_is_logged_to_file(monkeypatch) -> None:
    """recorder.__main__과 같은 방식으로, 재시작 사유가 실제 로그 파일에 남아야 한다
    (이전에는 supervisor가 아무 로그도 안 남겼음)."""
    monkeypatch.setattr(sys, "argv", ["supervisor"])

    with (
        patch("recorder.supervisor.subprocess.run") as mock_run,
        patch("recorder.supervisor.time.sleep"),
    ):
        mock_run.side_effect = [MagicMock(returncode=1), MagicMock(returncode=0)]
        supervisor.main()

    for handler in supervisor.logger.handlers:
        handler.flush()
    log_content = supervisor.DEFAULT_LOG_PATH.read_text(encoding="utf-8")

    assert "exit code 1" in log_content
    assert "재시작" in log_content
    assert "정상 종료" in log_content
