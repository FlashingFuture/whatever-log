import sys
from unittest.mock import patch

import pytest
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from sync_agent import supervisor


@pytest.fixture(autouse=True)
def _use_temp_log_path(tmp_path, monkeypatch):
    """실제 sync-supervisor.log를 건드리지 않고 임시 파일로 로깅하게 한다."""
    monkeypatch.setattr(supervisor, "DEFAULT_LOG_PATH", tmp_path / "sync-supervisor.log")
    yield
    supervisor.logger.handlers.clear()


@pytest.mark.parametrize(
    ("exit_code", "fragment"),
    [(0, "정상 종료"), (EXIT_ARGUMENT_ERROR, "인자가 잘못되었습니다"), (EXIT_ALREADY_RUNNING, "이미 실행 중")],
)
def test_known_exit_codes_stop_the_supervisor(exit_code, fragment) -> None:
    reason = supervisor._classify_exit(exit_code)

    assert reason is not None and fragment in reason


def test_other_exit_codes_are_crashes_to_retry() -> None:
    assert supervisor._classify_exit(1) is None
    assert supervisor._classify_exit(-9) is None


def test_main_passes_the_arguments_to_the_agent(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["supervisor", "--interval", "60"])

    with patch("sync_agent.supervisor.supervise") as supervise:
        supervisor.main()

    command = supervise.call_args.args[0]
    assert command == [sys.executable, "-m", "sync_agent", "--interval", "60"]
    assert supervise.call_args.kwargs["classify_exit"] is supervisor._classify_exit
