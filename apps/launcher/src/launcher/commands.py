"""launcher의 동작들: install / uninstall / start / stop / status.

각 동작은 한 일을 한 줄씩 `say`로 알린다(콘솔 창 없이 도는 pythonw에서는 sys.stdout이 없어 `say`가 아무것도 안 한다). 설치는 여러 번
실행해도 같은 결과여야 하고(이미 된 것은 그대로 두고), `dry_run`이면 아무것도 바꾸지 않고 할 일만 보여 준다.
"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from supervision import autostart as run_key
from supervision.autostart import pythonw_path

from launcher import components, shortcuts, ui_build
from launcher.components import COMPONENTS, Component

Say = Callable[[str], None]


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
                started = components.start(component)
                say(f"{component.label}: {'지금 시작했어요.' if started else '이미 실행 중이에요.'}")

    for problem in problems:
        say(f"문제: {problem}")
    if not problems:
        say("끝났어요. 시작 메뉴의 'whatever.log'를 열거나 `whatever-log start`로 창을 열 수 있어요.")
    return not problems


def uninstall(say: Say, *, dry_run: bool = False) -> bool:
    """실행 중인 구성 요소를 끄고 자동 시작·바로가기를 지운다. 기록·목표 같은 데이터와 로그인 정보는 그대로 둔다."""
    prefix = "[미리보기] " if dry_run else ""
    for component in COMPONENTS:
        if dry_run:
            say(f"{prefix}{component.label}: 끄고 자동 시작 등록을 지웁니다.")
            continue
        stopped = components.stop(component)
        run_key.disable(component.run_key_value)
        say(f"{component.label}: {'껐고, ' if stopped else ''}자동 시작 등록을 지웠어요.")
    for label, directory in (("시작 메뉴", shortcuts.start_menu_dir), ("바탕화면", shortcuts.desktop_dir)):
        if dry_run:
            say(f"{prefix}{label}: 바로가기를 지웁니다(있다면).")
        else:
            try:
                removed = shortcuts.remove(directory())
            except (OSError, subprocess.CalledProcessError):
                removed = False
            say(f"{label}: {'바로가기를 지웠어요.' if removed else '바로가기가 없어요.'}")
    say("기록·목표 데이터와 로그인 정보는 지우지 않았어요(로그인 정보는 앱에서 로그아웃하면 지워져요).")
    return True


def start(say: Say, *, open_window: bool = True) -> None:
    """꺼져 있는 백그라운드 구성 요소를 띄우고, 창을 연다(창이 닫힐 때까지 기다린다)."""
    for component in COMPONENTS:
        if components.start(component):
            say(f"{component.label}: 시작했어요.")
    if open_window:
        subprocess.run([str(pythonw_path()), "-m", "desktop"], cwd=components.REPO_ROOT, check=False)


def stop(say: Say) -> None:
    """백그라운드 구성 요소(기록기, 동기화 에이전트)를 끈다. 열려 있는 창은 그대로다(창을 닫으면 hub도 함께 끝난다)."""
    for component in COMPONENTS:
        count = components.stop(component)
        say(f"{component.label}: {'껐어요.' if count else '실행 중이 아니었어요.'}")


def _status_line(component: Component) -> str:
    pids = components.running_pids(component)
    running = f"실행 중(pid {', '.join(map(str, pids))})" if pids else "꺼져 있음"
    registered = "자동 시작 등록됨" if run_key.is_enabled(component.run_key_value) else "자동 시작 등록 안 됨"
    return f"{component.label}: {running} · {registered}"


def status(say: Say) -> None:
    """구성 요소별 실행 여부·자동 시작 등록 여부와 화면 빌드·바로가기 상태를 보여 준다(아무것도 바꾸지 않는다)."""
    for component in COMPONENTS:
        say(_status_line(component))
    say(f"화면: {'빌드됨' if ui_build.is_built() else '빌드 안 됨(`whatever-log install`이 빌드합니다)'}")
    link: Path = shortcuts.start_menu_dir() / shortcuts.SHORTCUT_NAME
    say(f"시작 메뉴 바로가기: {'있음' if link.exists() else '없음'}")
    say(f"파이썬: {sys.executable}")
