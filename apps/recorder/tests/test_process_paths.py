import os
from pathlib import Path

import psutil

from recorder.process_paths import resolve_exe_paths


def test_resolves_the_path_of_a_running_process() -> None:
    """지금 돌고 있는 이 테스트 프로세스의 이름으로 경로를 찾을 수 있어야 한다."""
    me = psutil.Process(os.getpid())

    paths = resolve_exe_paths({me.name()})

    assert Path(paths[me.name()]).exists()
    assert Path(paths[me.name()]).name == me.name()


def test_unknown_names_are_omitted_and_empty_input_is_cheap() -> None:
    assert resolve_exe_paths({"definitely-not-running-9f3a.exe"}) == {}
    assert resolve_exe_paths(set()) == {}
