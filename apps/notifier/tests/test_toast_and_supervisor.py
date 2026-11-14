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


# --- 박동 감시(supervisor가 받아서 처리한다) ---


def test_the_supervisor_watches_the_heartbeat_with_a_window_scaled_to_the_interval(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["supervisor"])
    with patch("notifier.supervisor.supervise") as supervise:
        supervisor.main()
    heartbeat = supervise.call_args.kwargs["heartbeat"]
    assert heartbeat.path == supervisor.HEARTBEAT_PATH
    assert heartbeat.stale_after_seconds == 5 * supervisor.AGENT_DEFAULT_INTERVAL_SECONDS == 300.0  # 기본 주기 60초의 5배
    assert heartbeat.startup_grace_seconds == supervisor.STARTUP_GRACE_SECONDS


@pytest.mark.parametrize(
    ("argv", "interval"),
    [
        ([], 60.0),
        (["--interval", "120"], 120.0),
        (["--interval=300"], 300.0),
        (["--once", "--interval", "30"], 30.0),
        (["--interval"], 60.0),  # 값이 없다 — 에이전트가 인자 오류로 끝난다
        (["--interval", "abc"], 60.0),
        (["--interval", "0"], 60.0),
        (["--interval", "-5"], 60.0),
        (["--interval", "inf"], 60.0),
    ],
)
def test_the_interval_is_read_from_the_agent_arguments(argv, interval) -> None:
    assert supervisor._interval_from(argv) == interval


def test_a_longer_interval_widens_the_allowed_silence() -> None:
    assert supervisor.heartbeat_for(["--interval", "600"]).stale_after_seconds == 3000.0
    assert supervisor.heartbeat_for(["--interval", "5"]).stale_after_seconds == supervisor.MIN_STALE_SECONDS


def test_the_supervisor_default_interval_matches_the_agent() -> None:
    from notifier import __main__ as agent

    assert supervisor.AGENT_DEFAULT_INTERVAL_SECONDS == agent.DEFAULT_INTERVAL_SECONDS


def test_the_agent_beats_every_cycle_even_when_the_check_fails(tmp_path, monkeypatch) -> None:
    from notifier import __main__ as agent

    beats: list[str] = []
    monkeypatch.setattr(agent, "beat", lambda: beats.append("beat"))
    monkeypatch.setattr(agent, "check_once", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    calls: list[float] = []

    def sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        agent.main(["--lock-path", str(tmp_path / "n.lock"), "--log-path", str(tmp_path / "n.log")], sleep=sleep)
    assert len(beats) == 4  # 주기마다 확인 전 한 번, 확인 뒤 한 번 — 확인이 실패해도 돌고 있다는 신호는 낸다
