import logging
import sys
import time
from pathlib import Path

import pytest

from supervision.heartbeat import (
    ENV_VAR,
    SUSPEND_GAP_SECONDS,
    Heartbeat,
    HeartbeatWatch,
    age_seconds,
    beat,
)
from supervision.supervisor import supervise

logger = logging.getLogger("test_heartbeat")


def _heartbeat(tmp_path: Path, *, stale=10.0, grace=30.0) -> Heartbeat:
    return Heartbeat(path=tmp_path / "x.heartbeat", stale_after_seconds=stale, startup_grace_seconds=grace)


class _Mtime:
    """파일 대신 쓰는 가짜 수정 시각. None이면 파일이 없다."""

    def __init__(self) -> None:
        self.value: int | None = None

    def __call__(self, _path: Path) -> int | None:
        return self.value


# --- 설정 검증 ---


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_the_allowed_times_must_be_finite_and_positive(tmp_path, bad) -> None:
    with pytest.raises(ValueError):
        _heartbeat(tmp_path, stale=bad)
    with pytest.raises(ValueError):
        _heartbeat(tmp_path, grace=bad)


# --- beat()와 age_seconds() ---


def test_beat_touches_the_file_the_supervisor_named(tmp_path, monkeypatch) -> None:
    path = tmp_path / "deep" / "agent.heartbeat"
    monkeypatch.setenv(ENV_VAR, str(path))
    beat()
    assert path.exists()


def test_beat_does_nothing_without_a_supervisor(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    beat()  # 예외 없이 끝난다


def test_beat_never_raises_when_the_file_cannot_be_written(tmp_path, monkeypatch) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv(ENV_VAR, str(blocker / "child.heartbeat"))  # 부모가 파일이라 만들 수 없다
    beat()


def test_age_is_none_without_a_file_and_grows_with_time(tmp_path) -> None:
    path = tmp_path / "a.heartbeat"
    assert age_seconds(path) is None
    path.write_text("")
    modified = path.stat().st_mtime
    assert age_seconds(path, now=lambda: modified + 42.0) == pytest.approx(42.0)
    assert age_seconds(path, now=lambda: modified - 5.0) == 0.0  # 시계가 뒤로 가도 음수로 보이지 않는다


# --- HeartbeatWatch: 시계와 파일을 주입해 시험한다 ---


def _hung_at(watch: HeartbeatWatch, target: float, *, start: float = 0.0, step: float = 1.0) -> bool:
    """실제 감시 루프처럼 짧은 간격으로 시계를 흘려 보내며 target 시각의 판정을 돌려준다(한 번에 크게 건너뛰면 절전으로 본다)."""
    now = start
    result = watch.is_hung(now)
    while now < target:
        now = min(target, now + step)
        result = watch.is_hung(now)
    return result


def test_a_silent_child_is_hung_only_after_the_startup_grace(tmp_path) -> None:
    mtime = _Mtime()
    watch = HeartbeatWatch(_heartbeat(tmp_path, stale=10, grace=30), started_at=0.0, read_modified=mtime)
    assert _hung_at(watch, 29.0) is False  # 시작 직후에는 첫 박동을 기다려 준다
    assert watch.is_hung(31.0) is True


def test_after_the_first_beat_the_shorter_stale_time_applies(tmp_path) -> None:
    mtime = _Mtime()
    watch = HeartbeatWatch(_heartbeat(tmp_path, stale=10, grace=30), started_at=0.0, read_modified=mtime)
    mtime.value = 100
    assert watch.is_hung(5.0) is False  # 첫 박동
    assert watch.is_hung(14.0) is False
    assert watch.is_hung(16.0) is True  # 박동이 10초 넘게 끊겼다


def test_each_new_beat_restarts_the_count(tmp_path) -> None:
    mtime = _Mtime()
    watch = HeartbeatWatch(_heartbeat(tmp_path, stale=10, grace=30), started_at=0.0, read_modified=mtime)
    for step in range(1, 30):  # 9초마다 박동 — 오래 돌아도 멈춘 것이 아니다
        mtime.value = step
        assert watch.is_hung(step * 9.0) is False


def test_an_old_file_from_the_previous_run_is_not_a_beat(tmp_path) -> None:
    heartbeat = _heartbeat(tmp_path, stale=10, grace=30)
    heartbeat.path.write_text("old")
    watch = HeartbeatWatch(heartbeat, started_at=0.0)  # 시작하면서 지운다
    assert not heartbeat.path.exists()
    assert _hung_at(watch, 31.0) is True


def test_an_undeletable_old_file_is_not_a_beat_either(tmp_path, monkeypatch) -> None:
    heartbeat = _heartbeat(tmp_path, stale=10, grace=30)
    mtime = _Mtime()
    mtime.value = 7  # 지우지 못해 남은 낡은 파일
    monkeypatch.setattr(Path, "unlink", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError()))
    watch = HeartbeatWatch(heartbeat, started_at=0.0, read_modified=mtime)
    assert _hung_at(watch, 31.0) is True  # 값이 바뀌지 않았으니 박동이 아니다
    mtime.value = 8
    assert watch.is_hung(32.0) is False  # 바뀌었다 = 박동


def test_a_stalled_watch_loop_is_treated_as_a_suspend_not_a_hang(tmp_path) -> None:
    """절전에서 깨어난 직후: 감시 루프가 오래 멈췄다 돌아왔다면 자식도 못 돌았으니, 허용 시간을 처음부터 다시 센다."""
    mtime = _Mtime()
    watch = HeartbeatWatch(_heartbeat(tmp_path, stale=10, grace=30), started_at=0.0, read_modified=mtime)
    mtime.value = 1
    assert watch.is_hung(1.0) is False
    woke_at = 3600.0  # 한 시간 잤다
    assert woke_at - 1.0 > SUSPEND_GAP_SECONDS
    assert watch.is_hung(woke_at) is False
    assert watch.is_hung(woke_at + 9.0) is False
    assert watch.is_hung(woke_at + 11.0) is True  # 깨어난 뒤에도 박동이 없으면 그때부터 센다


def test_a_vanished_beat_file_does_not_count_as_a_beat(tmp_path) -> None:
    mtime = _Mtime()
    watch = HeartbeatWatch(_heartbeat(tmp_path, stale=10, grace=30), started_at=0.0, read_modified=mtime)
    mtime.value = 1
    assert watch.is_hung(1.0) is False
    mtime.value = None  # 누가 지웠다
    assert _hung_at(watch, 12.0, start=1.0) is True


# --- supervise() 통합: 실제 자식 프로세스 ---

_HANG = "import time; time.sleep(60)"
_BEATING = "import time\nfrom supervision.heartbeat import beat\nfor _ in range(12):\n    beat()\n    time.sleep(0.1)"
_BEAT_THEN_HANG = "import time\nfrom supervision.heartbeat import beat\nbeat()\ntime.sleep(60)"


def _run(code: str, tmp_path: Path, *, stale: float, grace: float, **kwargs):
    seen_exit_codes: list[int] = []

    def classify(exit_code: int):
        seen_exit_codes.append(exit_code)
        return "정상 종료" if exit_code == 0 else None

    started = time.monotonic()
    supervise(
        [sys.executable, "-c", code],
        logger=logger,
        classify_exit=classify,
        restart_delay_seconds=0.01,
        heartbeat=_heartbeat(tmp_path, stale=stale, grace=grace),
        **kwargs,
    )
    return seen_exit_codes, time.monotonic() - started


def test_a_child_that_never_beats_is_killed_restarted_and_finally_given_up_on(tmp_path) -> None:
    seen, elapsed = _run(_HANG, tmp_path, stale=0.5, grace=0.5, max_consecutive_failures=2)
    assert seen == []  # 우리가 죽인 것은 종료 코드를 분류하지 않고 크래시로 센다
    assert elapsed < 20  # 60초를 기다리지 않았다


def test_a_child_that_beats_then_hangs_is_killed_after_the_stale_time(tmp_path) -> None:
    seen, elapsed = _run(_BEAT_THEN_HANG, tmp_path, stale=1.0, grace=30.0, max_consecutive_failures=1)
    assert seen == []
    assert elapsed < 25  # 시작 유예(30초)가 아니라 박동이 끊긴 허용 시간(1초)이 적용됐다


def test_a_child_that_keeps_beating_is_left_alone(tmp_path) -> None:
    seen, _ = _run(_BEATING, tmp_path, stale=0.8, grace=5.0)
    assert seen == [0]  # 한 번도 죽지 않고 스스로 정상 종료했다


def test_without_a_heartbeat_the_supervisor_behaves_as_before(tmp_path) -> None:
    seen: list[int] = []
    supervise(
        [sys.executable, "-c", "pass"],
        logger=logger,
        classify_exit=lambda code: seen.append(code) or "정상 종료",
    )
    assert seen == [0]


def test_the_child_is_told_where_to_beat(tmp_path) -> None:
    out = tmp_path / "env.txt"
    code = f"import os; open({str(out)!r}, 'w').write(os.environ.get({ENV_VAR!r}, 'missing'))"
    _run(code, tmp_path, stale=5.0, grace=5.0)
    assert out.read_text() == str(tmp_path / "x.heartbeat")


def test_a_run_that_never_beat_is_not_a_stable_run_even_when_the_grace_is_long(tmp_path) -> None:
    """시작 유예(여기서는 1.5초)가 안정 실행 시간(0.5초)보다 길면, 첫 박동 없이 멈춘 실행이 안정 실행으로 세어져 연속 실패가 리셋되고 영원히 포기하지 못한다."""
    import threading

    stop = threading.Event()
    timer = threading.Timer(25.0, stop.set)  # 고치기 전 코드라면 영원히 도는 루프를 끝내는 안전장치
    timer.start()
    try:
        started = time.monotonic()
        supervise(
            [sys.executable, "-c", _HANG],
            logger=logger,
            classify_exit=lambda code: None,
            restart_delay_seconds=0.01,
            heartbeat=_heartbeat(tmp_path, stale=1.0, grace=1.5),
            min_stable_run_seconds=0.5,
            max_consecutive_failures=3,
            stop_event=stop,
        )
        elapsed = time.monotonic() - started
    finally:
        timer.cancel()
    assert not stop.is_set()  # 안전장치가 아니라 스스로 포기했다
    assert elapsed < 20


def test_the_watch_reports_whether_the_child_ever_beat(tmp_path) -> None:
    mtime = _Mtime()
    watch = HeartbeatWatch(_heartbeat(tmp_path), started_at=0.0, read_modified=mtime)
    assert watch.has_beaten is False
    mtime.value = 5
    watch.is_hung(1.0)
    assert watch.has_beaten is True
