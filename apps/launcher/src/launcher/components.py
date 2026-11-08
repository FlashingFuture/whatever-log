"""launcher가 다루는 백그라운드 구성 요소(기록기, 동기화 에이전트)와 그 프로세스를 찾고·띄우고·끄는 일.

두 구성 요소 모두 `supervisor → 실제 프로그램` 두 겹이다. 끌 때는 supervisor를 먼저 꺼야 한다 — 프로그램만 끄면 supervisor가
크래시로 보고 다시 띄우고, supervisor만 끄면 프로그램이 혼자 남는다.

프로세스는 "이 가상환경의 파이썬으로 `-m <모듈>`을 실행 중인 것"으로 알아본다. 다른 폴더의 설치본이나 같은 이름의 다른 프로그램은
건드리지 않는다.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil
from recorder.autostart import VALUE_NAME as RECORDER_RUN_VALUE
from supervision.autostart import module_command, pythonw_path
from sync_agent.supervisor import AUTOSTART_VALUE_NAME as SYNC_RUN_VALUE

#: 저장소 루트(자식 프로세스의 작업 폴더). apps/launcher/src/launcher/components.py 기준.
REPO_ROOT = Path(__file__).resolve().parents[4]

_DETACHED = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
_STOP_WAIT_SECONDS = 5.0


@dataclass(frozen=True)
class Component:
    """백그라운드로 도는 구성 요소 하나. 이름은 사용자에게 보이고, 모듈 이름은 프로세스를 알아보고 띄우는 데 쓴다."""

    name: str
    label: str
    supervisor_module: str
    program_module: str
    run_key_value: str

    def autostart_command(self) -> str:
        """로그인 시 실행할 명령(콘솔 창 없이 supervisor를 띄운다)."""
        return module_command(self.supervisor_module)


RECORDER = Component("recorder", "기록기", "recorder.supervisor", "recorder", RECORDER_RUN_VALUE)
SYNC = Component("sync", "동기화 에이전트", "sync_agent.supervisor", "sync_agent", SYNC_RUN_VALUE)
COMPONENTS = (RECORDER, SYNC)


def _runs_module(command_line: list[str], module: str, scripts_dir: Path) -> bool:
    """명령줄이 "이 가상환경의 파이썬으로 -m module"인지."""
    if len(command_line) < 3 or "-m" not in command_line[1:]:
        return False
    if Path(command_line[0]).parent.resolve() != scripts_dir:
        return False
    position = command_line.index("-m")
    return position + 1 < len(command_line) and command_line[position + 1] == module


def find_processes(module: str, *, scripts_dir: Path | None = None) -> list[psutil.Process]:
    """이 가상환경에서 `-m module`로 실행 중인 프로세스들(venv 실행기와 실제 파이썬이 둘 다 잡힐 수 있다)."""
    scripts = (scripts_dir or Path(sys.executable).parent).resolve()
    found = []
    for process in psutil.process_iter(["cmdline"]):
        try:
            if _runs_module(process.info["cmdline"] or [], module, scripts):
                found.append(process)
        except (psutil.Error, OSError):
            continue
    return found


def running_pids(component: Component) -> list[int]:
    """구성 요소의 supervisor나 프로그램이 떠 있으면 그 pid들(없으면 빈 목록)."""
    processes = find_processes(component.supervisor_module) + find_processes(component.program_module)
    return sorted({process.pid for process in processes})


def start(component: Component) -> bool:
    """supervisor를 콘솔 창 없이 따로 떼어 띄운다(이 도구가 끝나도 계속 돈다). 이미 떠 있으면 아무것도 하지 않고 False."""
    if running_pids(component):
        return False
    subprocess.Popen(
        [str(pythonw_path()), "-m", component.supervisor_module],
        cwd=REPO_ROOT,
        creationflags=_DETACHED,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return True


def _terminate(processes: list[psutil.Process]) -> None:
    """정중히 종료를 요청하고, 시간 안에 안 끝나면 강제로 끝낸다."""
    for process in processes:
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=_STOP_WAIT_SECONDS)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass


def stop(component: Component) -> int:
    """supervisor를 먼저, 그다음 프로그램을 끈다. 끈 프로세스 수를 돌려준다."""
    supervisors = find_processes(component.supervisor_module)
    _terminate(supervisors)
    programs = find_processes(component.program_module)
    _terminate(programs)
    return len(supervisors) + len(programs)
