import subprocess
import sys
from unittest.mock import patch

import pytest
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from notifier import supervisor, toast


@pytest.fixture(autouse=True)
def _no_registry_and_temp_log(tmp_path, monkeypatch):
    """실제 레지스트리와 로그 파일을 건드리지 않는다."""
    monkeypatch.setattr(toast, "register_app_id", lambda: None)
    monkeypatch.setattr(supervisor, "DEFAULT_LOG_PATH", tmp_path / "notifier-supervisor.log")
    yield
    supervisor.logger.handlers.clear()


def _completed(returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


def test_the_text_travels_in_environment_variables_never_in_the_command() -> None:
    nasty = "'$(calc)\" ; Remove-Item *"
    with patch("notifier.toast.subprocess.run", return_value=_completed()) as run:
        assert toast.show_toast(nasty, "본문 `x`") is True

    command = run.call_args.args[0]
    assert nasty not in " ".join(command) and "본문" not in " ".join(command)
    environment = run.call_args.kwargs["env"]
    assert environment[toast._TITLE_VARIABLE] == nasty and environment[toast._BODY_VARIABLE] == "본문 `x`"
    assert run.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW  # 콘솔 창이 깜빡이지 않는다
    assert command[0].lower().endswith("powershell.exe")


def test_a_failing_powershell_returns_false_without_raising() -> None:
    with patch("notifier.toast.subprocess.run", return_value=_completed(1, "boom")):
        assert toast.show_toast("a", "b") is False


@pytest.mark.parametrize("error", [OSError("no powershell"), subprocess.TimeoutExpired("powershell", 20)])
def test_a_missing_or_hung_powershell_returns_false(error) -> None:
    with patch("notifier.toast.subprocess.run", side_effect=error):
        assert toast.show_toast("a", "b") is False


def test_an_unregisterable_app_id_does_not_stop_the_toast(monkeypatch) -> None:
    def fail() -> None:
        raise OSError("denied")

    monkeypatch.setattr(toast, "register_app_id", fail)
    with patch("notifier.toast.subprocess.run", return_value=_completed()):
        assert toast.show_toast("a", "b") is True


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
    with patch("notifier.supervisor.supervise") as supervise:
        supervisor.main()
    assert supervise.call_args.args[0] == [sys.executable, "-m", "notifier", "--interval", "60"]
    assert supervise.call_args.kwargs["classify_exit"] is supervisor._classify_exit
