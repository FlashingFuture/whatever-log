import os
from pathlib import Path

import psutil

from recorder.process_paths import ProcessPathTracker, resolve_exe_paths


def test_resolves_the_path_of_a_running_process() -> None:
    """지금 돌고 있는 이 테스트 프로세스의 이름으로 경로를 찾을 수 있어야 한다."""
    me = psutil.Process(os.getpid())

    paths = resolve_exe_paths({me.name()})

    assert Path(paths[me.name()]).exists()
    assert Path(paths[me.name()]).name == me.name()


def test_unknown_names_are_omitted_and_empty_input_is_cheap() -> None:
    assert resolve_exe_paths({"definitely-not-running-9f3a.exe"}) == {}
    assert resolve_exe_paths(set()) == {}


def test_tracker_only_resolves_each_name_once_on_success() -> None:
    calls = []

    def resolve(names):
        calls.append(set(names))
        return {}

    tracker = ProcessPathTracker(resolve=resolve, save=lambda conn, paths: None)

    tracker.record_new(None, {"a.exe"})
    tracker.record_new(None, {"a.exe", "b.exe"})
    tracker.record_new(None, {"a.exe", "b.exe"})

    assert calls == [{"a.exe"}, {"b.exe"}]  # 못 구한 이름도 다시 훑지 않는다


def test_tracker_retries_after_a_transient_failure_then_gives_up() -> None:
    attempts = []

    def save(conn, paths):
        attempts.append(1)
        raise RuntimeError("database is locked")

    tracker = ProcessPathTracker(
        resolve=lambda names: {}, save=save, max_attempts=3
    )

    for _ in range(6):
        tracker.record_new(None, {"a.exe"})

    assert len(attempts) == 3  # 3번까지 재시도하고 포기, 그 뒤로는 시도하지 않는다


def test_tracker_recovers_when_a_retry_succeeds() -> None:
    state = {"fail": True}
    saved = []

    def save(conn, paths):
        if state["fail"]:
            raise RuntimeError("locked")
        saved.append(paths)

    tracker = ProcessPathTracker(
        resolve=lambda names: {"a.exe": "C:/a.exe"}, save=save
    )

    tracker.record_new(None, {"a.exe"})
    state["fail"] = False
    tracker.record_new(None, {"a.exe"})
    tracker.record_new(None, {"a.exe"})

    assert saved == [{"a.exe": "C:/a.exe"}]
