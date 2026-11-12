"""launcher의 동작들: install / uninstall / start / stop / status.

각 동작은 한 일을 한 줄씩 `say`로 알린다(콘솔 창 없이 도는 pythonw에서는 sys.stdout이 없어 `say`가 아무것도 안 한다). 설치는 여러 번
실행해도 같은 결과여야 하고(이미 된 것은 그대로 두고), `dry_run`이면 아무것도 바꾸지 않고 할 일만 보여 준다.

한 단계가 실패해도 나머지는 계속하고, 끝에서 무엇이 안 됐는지 알린 뒤 실패(False/0이 아닌 종료 코드)로 끝낸다 — 일부만 된 것을 성공이라고 하지 않는다.
"""

import ctypes
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from common import paths
from supervision import autostart as run_key
from supervision.autostart import pythonw_path

from launcher import components, shortcuts, ui_build
from launcher.components import COMPONENTS, Component

Say = Callable[[str], None]

_UNSUPERVISED_HINT = "{label}: 감독(supervisor) 없이 혼자 떠 있어요. 죽어도 다시 뜨지 않으니 `whatever-log stop` 뒤에 다시 시작해 주세요."
_BLOCKED_HINT = (
    "{label}: 다른 폴더의 설치본이 같은 데이터로 이미 실행 중이라 시작하지 못했어요. "
    "그 폴더에서 `whatever-log stop`을 실행한 뒤 다시 시작해 주세요."
)


def _report_start(component: Component, say: Say, problems: list[str]) -> None:
    """구성 요소를 시작하고 결과를 알린다. 시작하지 못하거나 감독 없이 떠 있으면 문제로 모은다."""
    try:
        result = components.start(component)
    except OSError as error:
        problems.append(f"{component.label} 시작: {error}")
        return
    if result == components.STARTED:
        say(f"{component.label}: 지금 시작했어요.")
    elif result == components.SUPERVISED:
        say(f"{component.label}: 이미 실행 중이에요.")
    elif result == components.BLOCKED:
        problems.append(_BLOCKED_HINT.format(label=component.label))
    else:
        problems.append(_UNSUPERVISED_HINT.format(label=component.label))


def install(
    say: Say,
    *,
    dry_run: bool = False,
    desktop_shortcut: bool = False,
    build_ui: bool = True,
    start_now: bool = True,
) -> bool:
    """자동 시작·바로가기를 등록하고 화면을 빌드하고 백그라운드 구성 요소를 띄운다. 모두 잘 됐으면 True.

    한 단계가 실패해도 나머지는 계속한다(예: Node가 없어 화면을 빌드하지 못해도 기록기 등록은 해 둔다) — 무엇이 안 됐는지는 끝에서 알린다.
    """
    problems: list[str] = []
    prefix = "[미리보기] " if dry_run else ""

    if build_ui:
        if ui_build.is_built():
            say("화면: 이미 빌드되어 있어요.")
        elif dry_run:
            say(f"{prefix}화면: 빌드합니다(pnpm install, pnpm build).")
        else:
            say("화면: 빌드하는 중… (처음 한 번, 1~2분)")
            try:
                ui_build.build()
                say("화면: 빌드했어요.")
            except ui_build.UiBuildError as error:
                problems.append(f"화면 빌드: {error}")

    for component in COMPONENTS:
        _take_over_from_another_install(component, say, problems, dry_run=dry_run)
        if dry_run:
            say(f"{prefix}{component.label}: 로그인할 때 자동으로 시작되게 등록합니다.")
            continue
        try:
            run_key.enable(component.run_key_value, component.autostart_command())
            say(f"{component.label}: 로그인할 때 자동으로 시작되게 등록했어요.")
        except OSError as error:
            problems.append(f"{component.label} 자동 시작 등록: {error}")

    targets = [("시작 메뉴", shortcuts.start_menu_dir)]
    if desktop_shortcut:
        targets.append(("바탕화면", shortcuts.desktop_dir))
    for label, directory in targets:
        if dry_run:
            say(f"{prefix}{label}: whatever.log 바로가기를 만듭니다.")
            continue
        try:
            say(f"{label}: 바로가기를 만들었어요 ({shortcuts.create(directory())}).")
        except (OSError, subprocess.CalledProcessError) as error:
            problems.append(f"{label} 바로가기: {error}")

    if start_now:
        for component in COMPONENTS:
            if dry_run:
                say(f"{prefix}{component.label}: 지금 시작합니다(이미 떠 있으면 그대로 둡니다).")
            else:
                _report_start(component, say, problems)

    for problem in problems:
        say(f"문제: {problem}")
    if not problems:
        say("끝났어요. 시작 메뉴의 'whatever.log'를 열거나 `whatever-log start`로 창을 열 수 있어요.")
    return not problems


def _take_over_from_another_install(component: Component, say: Say, problems: list[str], *, dry_run: bool) -> None:
    """이미 다른 폴더의 설치가 등록돼 있으면(예: 새 버전을 새 폴더에 푼 경우) 그 등록을 이 폴더로 넘겨받고, 그 설치본의 프로그램을 끈다.

    이전 폴더의 프로그램이 떠 있으면 같은 데이터의 lock을 잡고 있어서 이 폴더의 프로그램이 시작하지 못한다 — 예전에는 사용자가
    이전 폴더에서 `whatever-log stop`을 직접 해야 했다. 끄는 것은 **등록이 가리키던 가상환경의 프로세스뿐**이고, 그 밖의 설치본은
    건드리지 않는다.
    """
    try:
        previous = run_key.registered_command(component.run_key_value)
    except OSError:
        return
    if previous is None or previous == component.autostart_command():
        return
    prefix = "[미리보기] " if dry_run else ""
    say(f"{prefix}{component.label}: 다른 폴더의 설치({previous})가 등록돼 있었어요. 이 폴더로 바꿉니다.")
    previous_scripts = components.scripts_dir_of(previous)
    if previous_scripts is None or previous_scripts == components.this_scripts_dir():
        return
    if dry_run:
        say(f"{prefix}{component.label}: 그 폴더의 프로그램이 떠 있으면 끕니다.")
        return
    result = components.stop(component, scripts_dir=previous_scripts)
    if not result.ok:
        problems.append(_stop_failure(component, result))
    elif result.stopped:
        say(f"{component.label}: 이전 폴더에서 실행 중이던 것을 껐어요.")


def _unregister(component: Component, say: Say, problems: list[str]) -> None:
    """이 설치본이 등록한 자동 시작만 지운다. 다른 clone이 등록한 것은 그대로 둔다(그쪽 설치가 다음 로그인부터 안 뜨게 되므로)."""
    try:
        registered = run_key.registered_command(component.run_key_value)
        if registered is None:
            say(f"{component.label}: 자동 시작 등록이 없어요.")
        elif registered != component.autostart_command():
            say(f"{component.label}: 자동 시작이 다른 설치본({registered})을 가리켜서 그대로 뒀어요.")
        else:
            run_key.disable(component.run_key_value)
            say(f"{component.label}: 자동 시작 등록을 지웠어요.")
    except OSError as error:
        problems.append(f"{component.label} 자동 시작 등록 해제: {error}")


def _remove_shortcut(label: str, directory: Callable[[], Path], say: Say, problems: list[str]) -> None:
    """이 설치본의 바로가기를 지운다. 못 지우면 지웠다고 하지 않고 문제로 모은다."""
    try:
        removed = shortcuts.remove(directory())
        say(f"{label}: {'바로가기를 지웠어요.' if removed else '바로가기가 없어요.'}")
    except shortcuts.ForeignShortcut:
        say(f"{label}: 다른 설치본이 만든 바로가기라 그대로 뒀어요.")
    except (OSError, subprocess.CalledProcessError) as error:
        problems.append(f"{label} 바로가기 삭제: {error}")


def uninstall(say: Say, *, dry_run: bool = False) -> bool:
    """실행 중인 구성 요소를 끄고 이 설치본의 자동 시작·바로가기를 지운다. 기록·목표 같은 데이터와 로그인 정보는 그대로 둔다.

    하나가 실패해도 나머지는 계속하고, 하나라도 실패하면 False를 돌려준다.
    """
    problems: list[str] = []
    prefix = "[미리보기] " if dry_run else ""
    for component in COMPONENTS:
        if dry_run:
            say(f"{prefix}{component.label}: 끄고 자동 시작 등록을 지웁니다.")
            continue
        result = components.stop(component)
        if not result.ok:
            problems.append(_stop_failure(component, result))
        _unregister(component, say, problems)
    for label, directory in (("시작 메뉴", shortcuts.start_menu_dir), ("바탕화면", shortcuts.desktop_dir)):
        if dry_run:
            say(f"{prefix}{label}: 바로가기를 지웁니다(있다면).")
        else:
            _remove_shortcut(label, directory, say, problems)
    for problem in problems:
        say(f"문제: {problem}")
    if not dry_run:
        folder = paths.data_dir()
        where = f" ({folder})" if folder is not None else ""
        say(f"기록·목표 데이터{where}와 로그인 정보는 지우지 않았어요(로그인 정보는 앱에서 로그아웃하면 지워져요).")
    return not problems


def _stop_failure(component: Component, result: components.StopResult) -> str:
    return f"{component.label}: pid {', '.join(map(str, result.survivors))}를 끝내지 못했어요(권한이 없을 수 있어요). 작업 관리자에서 끝내 주세요."


def _show_message(text: str) -> None:
    """콘솔이 없을 때(시작 메뉴 바로가기는 pythonw로 돈다) 사용자가 볼 수 있게 대화 상자로 알린다."""
    ctypes.windll.user32.MessageBoxW(None, text, "whatever.log", 0x10)  # MB_ICONERROR


def _install_command() -> str:
    """사용자에게 보여 줄 설치 명령. 번들에서는 `whatever-log.cmd`, 개발용 저장소에서는 `uv run whatever-log`."""
    return "whatever-log.cmd install" if paths.bundle_info() is not None else "uv run whatever-log install"


def _desktop_log() -> Path:
    """창(desktop)의 로그 파일 위치. 번들에서는 사용자 데이터 폴더의 logs/, 개발용 저장소에서는 apps/desktop/ 안이다(common.paths와 같은 규칙)."""
    return paths.data_path(components.REPO_ROOT / "apps" / "desktop", "hub-supervisor.log", subdir="logs")


def start(say: Say, *, open_window: bool = True) -> bool:
    """꺼져 있는 백그라운드 구성 요소를 띄우고, 창을 연다(창이 닫힐 때까지 기다린다). 잘 됐으면 True.

    화면이 빌드되어 있지 않거나 창이 오류로 끝나면 그 사실과 복구 방법을 알린다 — 콘솔이 없으면 대화 상자로.
    """
    problems: list[str] = []
    for component in COMPONENTS:
        _report_start(component, say, problems)
    if open_window:
        if not ui_build.is_built():
            problems.append(f"화면이 아직 빌드되지 않았어요. `{_install_command()}`을 실행해 주세요.")
        else:
            completed = subprocess.run([str(pythonw_path()), "-m", "desktop"], cwd=components.REPO_ROOT, check=False)
            if completed.returncode != 0:
                problems.append(f"창이 오류로 끝났어요(종료 코드 {completed.returncode}). {_desktop_log()}를 확인해 주세요.")
    for problem in problems:
        say(f"문제: {problem}")
    if problems and sys.stdout is None:
        _show_message("\n".join(problems))
    return not problems


def stop(say: Say) -> bool:
    """백그라운드 구성 요소(기록기, 동기화 에이전트)를 끈다. 열려 있는 창은 그대로다(창을 닫으면 hub도 함께 끝난다). 다 껐으면 True."""
    ok = True
    for component in COMPONENTS:
        result = components.stop(component)
        if not result.ok:
            ok = False
            say(f"문제: {_stop_failure(component, result)}")
        else:
            say(f"{component.label}: {'껐어요.' if result.stopped else '실행 중이 아니었어요.'}")
    return ok


_STATE_TEXT = {
    components.STOPPED: "꺼져 있음",
    components.SUPERVISED: "실행 중",
    components.UNSUPERVISED: "감독 없이 혼자 실행 중(죽어도 다시 뜨지 않아요)",
}


def _status_line(component: Component) -> str:
    pids = components.running_pids(component)
    running = _STATE_TEXT[components.state(component)] + (f" (pid {', '.join(map(str, pids))})" if pids else "")
    registered = "자동 시작 등록됨" if run_key.is_enabled(component.run_key_value) else "자동 시작 등록 안 됨"
    return f"{component.label}: {running} · {registered}"


def status(say: Say) -> None:
    """구성 요소별 실행 여부·자동 시작 등록 여부와 화면 빌드·바로가기 상태를 보여 준다(아무것도 바꾸지 않는다)."""
    for component in COMPONENTS:
        say(_status_line(component))
    say(f"화면: {'빌드됨' if ui_build.is_built() else '빌드 안 됨(`whatever-log install`이 빌드합니다)'}")
    link: Path = shortcuts.start_menu_dir() / shortcuts.SHORTCUT_NAME
    say(f"시작 메뉴 바로가기: {'있음' if link.exists() else '없음'}")
    say(f"버전: {paths.version()}")
    folder = paths.data_dir()
    say(f"데이터 폴더: {folder if folder is not None else '앱 폴더 안(개발용 저장소)'}")
    say(f"파이썬: {sys.executable}")
