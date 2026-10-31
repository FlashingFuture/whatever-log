import sys
from unittest.mock import patch

import pytest

from recorder import supervisor
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR


@pytest.fixture(autouse=True)
def _use_temp_log_path(tmp_path, monkeypatch):
    """실제 apps/recorder/supervisor.log를 건드리지 않고 임시 파일로 로깅하게 한다."""
    monkeypatch.setattr(supervisor, "DEFAULT_LOG_PATH", tmp_path / "supervisor.log")
    yield
    supervisor.logger.handlers.clear()


def test_exit_codes_do_not_collide() -> None:
    """argparse 인자 오류와 중복 실행이 같은 종료 코드를 쓰면 구분할 수 없다."""
    assert EXIT_ARGUMENT_ERROR != EXIT_ALREADY_RUNNING


@pytest.mark.parametrize(
    ("exit_code", "expected_fragment"),
    [
        (0, "정상 종료"),
        (EXIT_ARGUMENT_ERROR, "인자가 잘못되었습니다"),
        (EXIT_ALREADY_RUNNING, "이미 실행 중"),
    ],
)
def test_classify_exit_recognizes_known_codes(exit_code, expected_fragment) -> None:
    """알고 있는 종료 코드는 재시작하지 않을 사유를 돌려줘야 한다 — 재시도해도
    안 풀리거나(인자 오류, 중복 실행) 더 돌 필요가 없는(정상 종료) 경우다."""
    reason = supervisor._classify_exit(exit_code)
    assert reason is not None
    assert expected_fragment in reason


def test_classify_exit_treats_unknown_codes_as_crashes() -> None:
    """모르는 종료 코드(디스크 꽉 참 등)는 크래시로 보고 None을 돌려줘서
    supervise()가 재시도하게 해야 한다. 재시작/포기 메커니즘 자체는
    packages/supervision에서 검증한다."""
    assert supervisor._classify_exit(1) is None


def test_passes_through_cli_args_and_wiring_to_supervise(monkeypatch) -> None:
    """supervisor 자신에게 들어온 인자를 recorder 자식 프로세스 커맨드에 그대로
    넘기고, classify_exit/logger를 올바르게 supervise()에 연결해야 한다."""
    monkeypatch.setattr(sys, "argv", ["supervisor", "--interval", "30", "--db-path", "x.db"])

    with patch("recorder.supervisor.supervise") as mock_supervise:
        supervisor.main()

    called_command = mock_supervise.call_args[0][0]
    assert called_command == [
        sys.executable,
        "-m",
        "recorder",
        "--interval",
        "30",
        "--db-path",
        "x.db",
    ]
    assert mock_supervise.call_args.kwargs["classify_exit"] is supervisor._classify_exit
    assert mock_supervise.call_args.kwargs["logger"] is supervisor.logger
