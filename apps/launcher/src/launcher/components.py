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


# 값을 따로 받는 파이썬 옵션(`-X utf8`, `-W ignore`처럼 다음 인자가 그 값이다). 이 값을 `-m`으로 오해하지 않으려고 건너뛴다.
_OPTIONS_WITH_VALUE = frozenset({"-X", "-W", "--check-hash-based-pycs"})


def _runs_module(command_line: list[str], module: str, scripts_dir: Path) -> bool:
    """명령줄이 "이 가상환경의 파이썬으로 -m module"인지.

    파이썬 **자신의 옵션** 자리의 `-m`만 센다. `python -c '...' -m recorder`나 `python script.py -m recorder`의 `-m recorder`는
    실행할 코드의 인자일 뿐이라 기록기가 아니다(그걸 기록기로 알아보면 status가 틀리고 stop이 관련 없는 프로세스를 끈다).
    """
    if len(command_line) < 3 or Path(command_line[0]).parent.resolve() != scripts_dir:
        return False
    options = iter(command_line[1:])
    for argument in options:
        if argument == "-m":
            return next(options, None) == module
        if argument in _OPTIONS_WITH_VALUE:
            next(options, None)  # 옵션의 값
        elif not argument.startswith("-") or argument in ("-c", "-"):
            return False  # 스크립트 파일이나 -c 코드가 나왔다 — 그 뒤는 코드의 인자다
    return False


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


#: 구성 요소의 상태. stopped: 아무것도 안 떠 있음 / supervised: supervisor가 떠 있음(죽으면 다시 띄운다) /
#: unsupervised: 프로그램만 떠 있음(수동으로 띄웠거나 supervisor만 죽음 — 프로그램이 죽어도 다시 뜨지 않는다)
STOPPED, SUPERVISED, UNSUPERVISED = "stopped", "supervised", "unsupervised"
#: start()가 새로 띄웠다는 뜻(이미 떠 있던 경우는 그 상태를 돌려준다)
STARTED = "started"


def state(component: Component) -> str:
    """구성 요소의 지금 상태(STOPPED / SUPERVISED / UNSUPERVISED)."""
    if find_processes(component.supervisor_module):
        return SUPERVISED
    return UNSUPERVISED if find_processes(component.program_module) else STOPPED


def running_pids(component: Component) -> list[int]:
    """구성 요소의 supervisor나 프로그램이 떠 있으면 그 pid들(없으면 빈 목록)."""
    processes = find_processes(component.supervisor_module) + find_processes(component.program_module)
    return sorted({process.pid for process in processes})


def start(component: Component) -> str:
    """supervisor를 콘솔 창 없이 따로 떼어 띄운다(이 도구가 끝나도 계속 돈다). 돌려주는 값: STARTED / SUPERVISED(이미 감독 중) / UNSUPERVISED.

    프로그램만 단독으로 떠 있으면(UNSUPERVISED) 띄우지 않는다 — supervisor를 새로 띄워도 프로그램의 중복 실행 lock 때문에 곧 멈추고,
    떠 있는 프로그램을 우리가 마음대로 끌 수도 없다. 호출부가 사용자에게 "stop 뒤에 다시 start"를 안내한다.
    """
    current = state(component)
    if current != STOPPED:
        return current
    subprocess.Popen(
        [str(pythonw_path()), "-m", component.supervisor_module],
        cwd=REPO_ROOT,
        creationflags=_DETACHED,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return STARTED


def _terminate(processes: list[psutil.Process]) -> list[psutil.Process]:
    """정중히 종료를 요청하고, 시간 안에 안 끝나면 강제로 끝낸다. 끝내 살아 있는(종료 권한이 없는 등) 프로세스들을 돌려준다."""
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
    _, still_alive = psutil.wait_procs(alive, timeout=_STOP_WAIT_SECONDS)
    return still_alive


@dataclass(frozen=True)
class StopResult:
    """stop의 결과: 끈 프로세스 수와, 끝내 끄지 못한 프로세스 pid들(권한 부족 등)."""

    stopped: int
    survivors: tuple[int, ...]

    @property
    def ok(self) -> bool:
        """하나도 남지 않고 다 껐는가."""
        return not self.survivors


def stop(component: Component) -> StopResult:
    """supervisor를 먼저, 그다음 프로그램을 끈다. 못 끈 프로세스가 있으면 결과에 담아 알린다(끈 척하지 않는다)."""
    supervisors = find_processes(component.supervisor_module)
    left = _terminate(supervisors)
    programs = find_processes(component.program_module)
    left += _terminate(programs)
    total = len(supervisors) + len(programs)
    return StopResult(total - len(left), tuple(sorted({process.pid for process in left})))
