import logging
import threading
import time
from unittest.mock import MagicMock, patch

from supervision.supervisor import MAX_CONSECUTIVE_FAILURES, supervise

logger = logging.getLogger("test_supervision")


def _mock_process(returncode: int) -> MagicMock:
    """바로 종료되는(poll()이 즉시 종료 코드를 돌려주는) 자식 프로세스 흉내."""
    process = MagicMock()
    process.poll.return_value = returncode
    process.returncode = returncode
    return process


def test_stops_when_classify_exit_returns_a_reason() -> None:
    """classify_exit가 사유를 돌려주면(정상 종료 등) 재시작하지 않고 멈춰야 한다."""
    with patch("supervision.supervisor.subprocess.Popen") as mock_popen:
        mock_popen.return_value = _mock_process(0)
        supervise(
            ["cmd"],
            logger=logger,
            classify_exit=lambda code: "정상 종료" if code == 0 else None,
        )

    mock_popen.assert_called_once()


def test_restarts_on_crash_then_stops_on_classified_exit() -> None:
    """classify_exit가 None을 돌려주면(크래시) 재시작하고, 이후 분류되는
    종료 코드를 받으면 멈춰야 한다."""
    with patch("supervision.supervisor.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = [_mock_process(1), _mock_process(0)]
        supervise(
            ["cmd"],
            logger=logger,
            classify_exit=lambda code: "정상 종료" if code == 0 else None,
            restart_delay_seconds=0.01,
        )

    assert mock_popen.call_count == 2


def test_gives_up_after_too_many_consecutive_crashes() -> None:
    """같은 식으로 계속 바로 죽으면(디스크 꽉 찬 경우 등) 영원히 재시도하지
    말고 포기해야 한다."""
    with patch("supervision.supervisor.subprocess.Popen") as mock_popen:
        mock_popen.return_value = _mock_process(1)
        supervise(
            ["cmd"],
            logger=logger,
            classify_exit=lambda code: None,
            restart_delay_seconds=0.01,
        )

    assert mock_popen.call_count == MAX_CONSECUTIVE_FAILURES


def test_long_stable_run_resets_the_consecutive_failure_count() -> None:
    """한동안 잘 버티다가 가끔 한 번씩 죽는 패턴은 크래시 루프가 아니므로,
    연속 실패 횟수가 리셋되어 cap에 걸리지 않고 계속 재시작되어야 한다."""
    crash_count = MAX_CONSECUTIVE_FAILURES * 2
    processes = [_mock_process(1) for _ in range(crash_count)] + [_mock_process(0)]

    # 매 실행이 min_stable_run_seconds보다 훨씬 오래 걸렸다고 보고되도록,
    # monotonic() 호출마다 큰 값만큼 증가시킨다(한 실행마다 시작/종료로 두 번
    # 호출됨).
    monotonic_values = iter(float(i) * 1000.0 for i in range(len(processes) * 2 + 1))

    with (
        patch("supervision.supervisor.subprocess.Popen", side_effect=processes) as mock_popen,
        patch(
            "supervision.supervisor.time.monotonic",
            side_effect=lambda: next(monotonic_values),
        ),
    ):
        supervise(
            ["cmd"],
            logger=logger,
            classify_exit=lambda code: "정상 종료" if code == 0 else None,
            restart_delay_seconds=0.01,
        )

    assert mock_popen.call_count == len(processes)


def test_stop_event_terminates_the_running_child_and_returns() -> None:
    """stop_event가 set되면, 아직 살아있는 자식 프로세스를 종료시키고 더
    재시작하지 않고 바로 리턴해야 한다."""
    stop_event = threading.Event()
    process = MagicMock()
    process.poll.return_value = None  # 계속 살아있는 것처럼 흉내

    def _set_stop_soon() -> None:
        time.sleep(0.05)
        stop_event.set()

    with patch("supervision.supervisor.subprocess.Popen", return_value=process):
        threading.Thread(target=_set_stop_soon, daemon=True).start()
        supervise(["cmd"], logger=logger, classify_exit=lambda code: None, stop_event=stop_event)

    process.terminate.assert_called_once()


def test_stop_event_kills_the_child_if_it_ignores_terminate() -> None:
    """terminate()에 5초 안에 안 죽으면(멈춰 있는 프로세스 등), 그냥 두고
    리턴하면 포트/lock을 쥔 채로 좀비가 남는다 — kill()로 강제 종료해야
    한다."""
    import subprocess

    stop_event = threading.Event()
    process = MagicMock()
    process.poll.return_value = None  # 계속 살아있는 것처럼 흉내
    process.wait.side_effect = [subprocess.TimeoutExpired(cmd="cmd", timeout=5), None]

    def _set_stop_soon() -> None:
        time.sleep(0.05)
        stop_event.set()

    with patch("supervision.supervisor.subprocess.Popen", return_value=process):
        threading.Thread(target=_set_stop_soon, daemon=True).start()
        supervise(["cmd"], logger=logger, classify_exit=lambda code: None, stop_event=stop_event)

    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2


def test_stop_event_set_before_start_never_launches_the_process() -> None:
    """이미 중지 요청이 와 있는 상태로 호출되면, 애초에 프로세스를 띄우지
    않아야 한다."""
    stop_event = threading.Event()
    stop_event.set()

    with patch("supervision.supervisor.subprocess.Popen") as mock_popen:
        supervise(["cmd"], logger=logger, classify_exit=lambda code: None, stop_event=stop_event)

    mock_popen.assert_not_called()
