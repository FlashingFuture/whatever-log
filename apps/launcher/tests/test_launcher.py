import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from launcher import commands, components, shortcuts, ui_build
from launcher.__main__ import build_parser
from launcher.components import RECORDER, SYNC

SCRIPTS = Path(sys.executable).parent.resolve()


def _cmd(*parts: str) -> list[str]:
    return [str(SCRIPTS / "pythonw.exe"), *parts]


# --- 프로세스를 알아보는 규칙 ---


@pytest.mark.parametrize(
    ("command_line", "expected"),
    [
        (_cmd("-m", "sync_agent.supervisor"), True),
        (_cmd("-m", "sync_agent.supervisor", "--interval", "60"), True),
        (_cmd("-m", "sync_agent"), False),  # 다른 모듈
        (_cmd("-m", "sync_agent.supervisor_other"), False),  # 이름이 비슷한 다른 모듈
        (_cmd("sync_agent.supervisor"), False),  # -m이 없다
        (_cmd("-m"), False),  # 모듈 이름이 없다
        (_cmd("-c", "print()", "-m", "sync_agent.supervisor"), False),  # -c 코드의 인자일 뿐이다
        (_cmd("script.py", "-m", "sync_agent.supervisor"), False),  # 스크립트의 인자일 뿐이다
        (_cmd("-u", "-m", "sync_agent.supervisor"), True),  # 파이썬 옵션 뒤의 -m은 맞다
        (_cmd("-X", "utf8", "-m", "sync_agent.supervisor"), True),  # 값을 받는 옵션을 건너뛴다
        (_cmd("-X", "-m", "sync_agent.supervisor"), False),  # -X의 값이 "-m"이다(모듈 실행이 아니다)
        (["C:/elsewhere/.venv/Scripts/pythonw.exe", "-m", "sync_agent.supervisor"], False),  # 다른 설치본
        ([], False),
    ],
)
def test_a_process_is_recognized_only_when_this_environment_runs_that_module(command_line, expected) -> None:
    assert components._runs_module(command_line, "sync_agent.supervisor", SCRIPTS) is expected


def test_find_processes_returns_only_matching_processes_and_survives_vanished_ones() -> None:
    mine = MagicMock(info={"cmdline": _cmd("-m", "recorder")})
    other = MagicMock(info={"cmdline": ["notepad.exe"]})
    gone = MagicMock()
    type(gone).info = property(lambda self: (_ for _ in ()).throw(components.psutil.NoSuchProcess(1)))

    with patch("launcher.components.psutil.process_iter", return_value=[other, gone, mine]):
        assert components.find_processes("recorder") == [mine]


def test_running_pids_merges_supervisor_and_program_and_deduplicates() -> None:
    def fake(module, **_):
        return {"recorder.supervisor": [MagicMock(pid=3), MagicMock(pid=1)], "recorder": [MagicMock(pid=3)]}[module]

    with patch("launcher.components.find_processes", side_effect=fake):
        assert components.running_pids(RECORDER) == [1, 3]


def test_state_tells_supervised_unsupervised_and_stopped_apart() -> None:
    def fake(modules):
        return lambda module, **_: [MagicMock()] if module in modules else []

    with patch("launcher.components.find_processes", side_effect=fake({"recorder.supervisor"})):
        assert components.state(RECORDER) == components.SUPERVISED
    with patch("launcher.components.find_processes", side_effect=fake({"recorder"})):
        assert components.state(RECORDER) == components.UNSUPERVISED
    with patch("launcher.components.find_processes", side_effect=fake(set())):
        assert components.state(RECORDER) == components.STOPPED


# --- 띄우고 끄기 ---


def test_start_does_nothing_when_the_component_is_already_supervised() -> None:
    with (
        patch("launcher.components.state", return_value=components.SUPERVISED),
        patch("launcher.components.subprocess.Popen") as popen,
    ):
        assert components.start(RECORDER) == components.SUPERVISED

    popen.assert_not_called()


def test_a_program_running_without_its_supervisor_is_reported_not_started_over() -> None:
    """supervisor를 새로 띄워도 프로그램의 중복 실행 lock 때문에 곧 멈춘다 — 감독이 복구된 것처럼 보이면 안 된다."""
    with (
        patch("launcher.components.state", return_value=components.UNSUPERVISED),
        patch("launcher.components.subprocess.Popen") as popen,
    ):
        assert components.start(SYNC) == components.UNSUPERVISED

    popen.assert_not_called()


def test_start_launches_the_supervisor_detached_without_a_console() -> None:
    with (
        patch("launcher.components.state", return_value=components.STOPPED),
        patch("launcher.components._lock_is_free", return_value=True),
        patch("launcher.components.subprocess.Popen") as popen,
    ):
        assert components.start(SYNC) == components.STARTED

    command = popen.call_args.args[0]
    assert command[1:] == ["-m", "sync_agent.supervisor"] and command[0].endswith("pythonw.exe")
    flags = popen.call_args.kwargs["creationflags"]
    assert flags & subprocess.DETACHED_PROCESS and flags & subprocess.CREATE_NO_WINDOW
    assert popen.call_args.kwargs["cwd"] == components.REPO_ROOT


def test_start_does_not_launch_when_another_install_holds_the_lock(tmp_path) -> None:
    """이 설치본의 프로세스는 없어도 다른 곳(다른 폴더의 설치본)이 lock을 잡고 있으면 띄우지 않는다 — 띄워도 바로 멈춘다."""
    lock = tmp_path / "recorder.db.lock"
    held = components.acquire_lock(lock)
    try:
        with (
            patch("launcher.components.state", return_value=components.STOPPED),
            patch("launcher.components.lock_path", return_value=lock),
            patch("launcher.components.subprocess.Popen") as popen,
        ):
            assert components.start(RECORDER) == components.BLOCKED
    finally:
        held.release()

    popen.assert_not_called()


def test_start_launches_once_the_lock_is_free_again(tmp_path) -> None:
    lock = tmp_path / "recorder.db.lock"
    components.acquire_lock(lock).release()  # 예전에 잡혔다가 풀린 lock 파일이 남아 있어도 막지 않는다
    with (
        patch("launcher.components.state", return_value=components.STOPPED),
        patch("launcher.components.lock_path", return_value=lock),
        patch("launcher.components.subprocess.Popen") as popen,
    ):
        assert components.start(RECORDER) == components.STARTED

    popen.assert_called_once()


def test_each_component_checks_its_own_programs_lock() -> None:
    from recorder.__main__ import DEFAULT_LOCK_PATH as recorder_lock
    from sync_agent.__main__ import DEFAULT_LOCK_PATH as sync_lock

    assert components.lock_path(RECORDER) == recorder_lock and recorder_lock.name == "recorder.db.lock"
    assert components.lock_path(SYNC) == sync_lock and sync_lock.name == "sync.lock"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('"C:\\Program Files\\old\\.venv\\Scripts\\pythonw.exe" -m recorder.supervisor', Path("C:/Program Files/old/.venv/Scripts")),
        ("C:\\old\\.venv\\Scripts\\pythonw.exe -m recorder.supervisor", Path("C:/old/.venv/Scripts")),
        ("C:\\old\\.venv\\Scripts\\python.exe -m recorder.supervisor", Path("C:/old/.venv/Scripts")),
        ('"C:\\Program Files\\old\\runtime\\whatever-log.exe" -m recorder.supervisor', Path("C:/Program Files/old/runtime")),  # 파이썬을 담았던 번들
        ("C:\\old\\runtime\\whatever-log-cli.exe -m launcher install", Path("C:/old/runtime")),
        ('"C:\\Tools\\other.exe" --flag', None),  # 파이썬이 아닌 것은 건드릴 대상이 아니다
        ("", None),
    ],
)
def test_the_install_folder_is_read_from_an_autostart_command(command, expected) -> None:
    assert components.scripts_dir_of(command) == (expected.resolve() if expected else None)


def test_stop_can_target_another_installs_environment() -> None:
    seen: list[Path | None] = []
    with (
        patch("launcher.components.find_processes", side_effect=lambda module, scripts_dir=None: seen.append(scripts_dir) or []),
        patch("launcher.components._terminate", return_value=[]),
    ):
        components.stop(RECORDER, scripts_dir=Path("C:/old/.venv/Scripts"))

    assert seen == [Path("C:/old/.venv/Scripts")] * 2


def test_stop_terminates_the_supervisor_before_the_program() -> None:
    order: list[str] = []

    def fake_find(module, **_):
        return [module]

    def fake_terminate(items):
        order.extend(items)
        return []

    with (
        patch("launcher.components.find_processes", side_effect=fake_find),
        patch("launcher.components._terminate", side_effect=fake_terminate),
    ):
        result = components.stop(SYNC)

    assert order == ["sync_agent.supervisor", "sync_agent"]  # supervisor가 먼저여야 프로그램을 다시 띄우지 못한다
    assert result.stopped == 2 and result.ok


def test_stop_reports_processes_it_could_not_end_instead_of_claiming_success() -> None:
    survivor = MagicMock(pid=42)
    with (
        patch("launcher.components.find_processes", side_effect=lambda module, **_: [survivor] if module == "recorder" else []),
        patch("launcher.components._terminate", side_effect=lambda items: list(items)),
    ):
        result = components.stop(RECORDER)

    assert not result.ok and result.survivors == (42,) and result.stopped == 0


def test_terminate_kills_what_ignored_terminate_and_returns_the_survivors() -> None:
    stubborn = MagicMock()
    with patch("launcher.components.psutil.wait_procs", side_effect=[([], [stubborn]), ([], [stubborn])]):
        assert components._terminate([stubborn]) == [stubborn]

    stubborn.terminate.assert_called_once()
    stubborn.kill.assert_called_once()


# --- 설치 ---


def _collect():
    lines: list[str] = []
    return lines, lines.append


def _install(*, start_result=components.STARTED, built=True, start_effect=None, **options):
    """install을 가짜 의존성으로 돌리고 (성공 여부, 출력 줄, mock들)을 돌려준다."""
    lines, say = _collect()
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.shortcuts.create", return_value=Path("x.lnk")) as create,
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.components.start", return_value=start_result, side_effect=start_effect) as start,
        patch("launcher.commands.ui_build.is_built", return_value=built),
        patch("launcher.commands.ui_build.build") as build,
    ):
        run_key.registered_command.return_value = None  # 처음 설치(다른 폴더의 등록 없음)
        ok = commands.install(say, **options)
    return ok, lines, run_key, create, start, build


def test_a_dry_run_changes_nothing() -> None:
    ok, lines, run_key, create, start, build = _install(built=False, dry_run=True, desktop_shortcut=True)

    assert ok is True
    run_key.enable.assert_not_called()
    create.assert_not_called()
    start.assert_not_called()
    build.assert_not_called()
    assert any("바탕화면" in line for line in lines) and all("미리보기" in line or "끝났어요" in line for line in lines)


def test_install_registers_both_components_makes_the_shortcut_and_starts_them() -> None:
    ok, _, run_key, create, start, _ = _install()

    assert ok is True
    assert [call.args[0] for call in run_key.enable.call_args_list] == [RECORDER.run_key_value, SYNC.run_key_value]
    assert run_key.enable.call_args_list[1].args[1].endswith("-m sync_agent.supervisor")
    create.assert_called_once_with(Path("menu"))
    assert start.call_count == 2


def test_one_failing_step_does_not_stop_the_rest_and_is_reported() -> None:
    lines, say = _collect()
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.shortcuts.create", return_value=Path("x.lnk")),
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.components.start", return_value=components.STARTED) as start,
        patch("launcher.commands.ui_build.is_built", return_value=False),
        patch("launcher.commands.ui_build.build", side_effect=ui_build.UiBuildError("Node.js가 없어요")),
    ):
        run_key.registered_command.return_value = None
        ok = commands.install(say)

    assert ok is False
    assert run_key.enable.call_count == 2 and start.call_count == 2  # 화면 빌드가 실패해도 나머지는 했다
    assert any(line.startswith("문제: 화면 빌드") and "Node.js" in line for line in lines)


def test_install_can_skip_the_ui_build_and_the_start() -> None:
    _, _, _, _, start, build = _install(built=False, build_ui=False, start_now=False)

    build.assert_not_called()
    start.assert_not_called()


def test_install_collects_a_start_failure_and_keeps_going() -> None:
    calls: list[str] = []

    def start(component):
        calls.append(component.name)
        if component is RECORDER:
            raise OSError("pythonw.exe를 실행할 수 없어요")
        return components.STARTED

    ok, lines, *_ = _install(start_effect=start)

    assert ok is False and calls == ["recorder", "sync"]  # 기록기가 실패해도 동기화 에이전트는 시작했다
    assert any(line.startswith("문제: 기록기 시작") for line in lines)


def test_install_reports_a_program_running_without_its_supervisor() -> None:
    ok, lines, *_ = _install(start_result=components.UNSUPERVISED)

    assert ok is False and any("감독" in line for line in lines)


def test_install_does_not_claim_it_started_what_another_install_blocks() -> None:
    """다른 폴더의 설치본이 같은 데이터로 떠 있으면 "지금 시작했어요"라고 하지 않고 무엇을 해야 하는지 알린다."""
    ok, lines, *_ = _install(start_result=components.BLOCKED)

    assert ok is False
    assert not any("지금 시작했어요" in line for line in lines)
    assert any(line.startswith("문제: 기록기") and "whatever-log stop" in line for line in lines)


# --- 제거 ---


def _own_registration(component):
    return component.autostart_command()


def _uninstall(*, stop_result=None, registered=_own_registration, remove=lambda directory: True):
    """uninstall을 가짜 의존성으로 돌리고 (성공 여부, 출력 줄, run_key mock)을 돌려준다."""
    lines: list[str] = []
    result = stop_result or components.StopResult(2, ())
    by_name = {RECORDER.run_key_value: RECORDER, SYNC.run_key_value: SYNC}
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.components.stop", return_value=result),
        patch("launcher.commands.shortcuts.remove", side_effect=remove),
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.shortcuts.desktop_dir", return_value=Path("desk")),
    ):
        run_key.registered_command.side_effect = lambda name: registered(by_name[name])
        ok = commands.uninstall(lines.append)
    return ok, lines, run_key


def test_uninstall_stops_unregisters_and_keeps_the_data() -> None:
    ok, lines, run_key = _uninstall()

    assert ok is True
    assert [call.args[0] for call in run_key.disable.call_args_list] == [RECORDER.run_key_value, SYNC.run_key_value]
    assert any("지우지 않았어요" in line for line in lines)


def test_uninstall_leaves_another_clones_autostart_registration_alone() -> None:
    """다른 clone이 등록한 자동 시작을 지우면 그쪽이 다음 로그인부터 안 뜬다."""
    ok, lines, run_key = _uninstall(registered=lambda component: "C:/other-clone/.venv/Scripts/pythonw.exe -m recorder.supervisor")

    assert ok is True
    run_key.disable.assert_not_called()
    assert any("다른 설치본" in line for line in lines)


def test_uninstall_does_nothing_for_a_registration_that_does_not_exist() -> None:
    ok, lines, run_key = _uninstall(registered=lambda component: None)

    assert ok is True
    run_key.disable.assert_not_called()
    assert any("등록이 없어요" in line for line in lines)


def test_uninstall_leaves_another_clones_shortcut_alone() -> None:
    def foreign(directory):
        raise shortcuts.ForeignShortcut("x.lnk")

    ok, lines, _ = _uninstall(remove=foreign)

    assert ok is True and any("다른 설치본이 만든 바로가기" in line for line in lines)


def test_uninstall_reports_a_shortcut_it_could_not_delete_and_fails() -> None:
    def denied(directory):
        raise PermissionError("access denied")

    ok, lines, run_key = _uninstall(remove=denied)

    assert ok is False
    assert any(line.startswith("문제: 시작 메뉴 바로가기 삭제") and "access denied" in line for line in lines)
    assert not any("바로가기를 지웠어요" in line for line in lines)  # 못 지웠는데 지웠다고 하지 않는다
    assert run_key.disable.call_count == 2  # 하나가 실패해도 나머지는 계속했다


def test_uninstall_fails_when_a_process_could_not_be_ended() -> None:
    ok, lines, _ = _uninstall(stop_result=components.StopResult(0, (42,)))

    assert ok is False and any("pid 42" in line and "끝내지 못했어요" in line for line in lines)


def test_a_dry_uninstall_changes_nothing() -> None:
    lines: list[str] = []
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.components.stop") as stop,
        patch("launcher.commands.shortcuts.remove") as remove,
    ):
        assert commands.uninstall(lines.append, dry_run=True) is True

    run_key.disable.assert_not_called()
    stop.assert_not_called()
    remove.assert_not_called()


# --- 시작·종료 ---


def _start(*, open_window=True, built=True, returncode=0, start_result=components.SUPERVISED, console=True):
    lines: list[str] = []
    with (
        patch("launcher.commands.components.start", return_value=start_result),
        patch("launcher.commands.ui_build.is_built", return_value=built),
        patch("launcher.commands.subprocess.run", return_value=MagicMock(returncode=returncode)) as run,
        patch("launcher.commands._show_message") as message,
        patch("launcher.commands.sys.stdout", MagicMock() if console else None),
    ):
        ok = commands.start(lines.append, open_window=open_window)
    return ok, lines, run, message


def test_start_without_a_window_only_starts_the_components() -> None:
    ok, _, run, _ = _start(open_window=False)

    assert ok is True
    run.assert_not_called()


def test_start_opens_the_desktop_window_with_pythonw() -> None:
    ok, _, run, _ = _start()

    assert ok is True and run.call_args.args[0][1:] == ["-m", "desktop"]


def test_start_tells_how_to_recover_when_the_ui_is_not_built_and_shows_a_dialog_without_a_console() -> None:
    ok, lines, run, message = _start(built=False, console=False)

    assert ok is False
    run.assert_not_called()  # 창이 열리지도 못하고 죽는 일을 미리 막는다
    assert any("whatever-log install" in line for line in lines)
    message.assert_called_once()
    assert "whatever-log install" in message.call_args.args[0]


def test_start_propagates_a_window_that_exits_with_an_error() -> None:
    ok, lines, _, message = _start(returncode=3, console=True)

    assert ok is False and any("종료 코드 3" in line for line in lines)
    message.assert_not_called()  # 콘솔이 있으면 대화 상자는 띄우지 않는다


def test_start_reports_a_program_running_without_its_supervisor() -> None:
    ok, lines, _, _ = _start(start_result=components.UNSUPERVISED, open_window=False)

    assert ok is False and any("감독" in line and "whatever-log stop" in line for line in lines)


def test_stop_reports_failure_and_still_tries_every_component() -> None:
    lines: list[str] = []
    results = iter([components.StopResult(0, (7,)), components.StopResult(1, ())])
    with patch("launcher.commands.components.stop", side_effect=lambda component: next(results)):
        ok = commands.stop(lines.append)

    assert ok is False
    assert any("pid 7" in line for line in lines) and any("껐어요" in line for line in lines)


# --- 화면 빌드 ---


def test_ui_build_reports_missing_node_in_plain_words() -> None:
    with patch("launcher.ui_build.shutil.which", return_value=None):
        with pytest.raises(ui_build.UiBuildError, match="Node.js"):
            ui_build.build()


def test_ui_build_reads_the_output_as_utf8_so_a_checkmark_cannot_break_the_install() -> None:
    """Vite가 찍는 ✓를 cp949로 읽으면 디코딩 오류로 설치가 중단된다."""
    ok = MagicMock(returncode=0, stdout="✓ built", stderr="")
    with (
        patch("launcher.ui_build.shutil.which", return_value="corepack"),
        patch("launcher.ui_build.subprocess.run", return_value=ok) as run,
    ):
        ui_build.build()

    assert run.call_count == 2
    for call in run.call_args_list:
        assert call.kwargs["encoding"] == "utf-8" and call.kwargs["errors"] == "replace"


def test_ui_build_failure_shows_the_tail_of_the_output() -> None:
    failed = MagicMock(returncode=1, stdout="", stderr="line1\nline2\nboom")
    with (
        patch("launcher.ui_build.shutil.which", return_value="corepack"),
        patch("launcher.ui_build.subprocess.run", return_value=failed),
    ):
        with pytest.raises(ui_build.UiBuildError, match="boom"):
            ui_build.build()


# --- 바로가기(실제 .lnk를 임시 폴더에 만든다) ---


def test_a_real_shortcut_points_at_pythonw_with_the_app_icon(tmp_path) -> None:
    link = shortcuts.create(tmp_path / "menu")

    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:WL_LINK);"
        "$s.TargetPath; $s.Arguments; $s.IconLocation"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        env={**os.environ, "WL_LINK": str(link)},
        capture_output=True,
        text=True,
        check=True,
    )
    target, arguments, icon = result.stdout.strip().splitlines()
    assert target.endswith("pythonw.exe") and arguments == "-m launcher start"
    assert icon.endswith("icon.ico,0") and Path(icon.rsplit(",", 1)[0]).is_file()
    assert shortcuts.remove(tmp_path / "menu") is True and shortcuts.remove(tmp_path / "menu") is False


def test_a_shortcut_made_by_this_install_is_recognized_as_ours(tmp_path) -> None:
    shortcuts.create(tmp_path)

    assert shortcuts.is_ours(tmp_path / shortcuts.SHORTCUT_NAME) is True


def test_a_shortcut_from_another_install_is_left_alone(tmp_path) -> None:
    """다른 clone이 만든 같은 이름의 바로가기를 지우면 그쪽 시작 메뉴 항목이 사라진다."""
    shortcuts.create(tmp_path)
    with patch("launcher.shortcuts.REPO_ROOT", Path("C:/somewhere/else")):
        with pytest.raises(shortcuts.ForeignShortcut):
            shortcuts.remove(tmp_path)

    assert (tmp_path / shortcuts.SHORTCUT_NAME).exists()


def test_the_desktop_folder_comes_from_the_windows_api() -> None:
    """PowerShell 출력을 문자열로 받으면 코드 페이지에 따라 한글 경로가 깨질 수 있어서 API를 유니코드 그대로 쓴다."""
    folder = shortcuts.desktop_dir()

    assert folder.is_dir() and folder.is_absolute()


# --- 명령줄 ---


def test_every_documented_command_parses() -> None:
    parser = build_parser()

    assert parser.parse_args(["install", "--dry-run", "--desktop-shortcut", "--skip-ui-build", "--no-start"]).dry_run
    assert parser.parse_args(["start", "--no-window"]).no_window
    for name in ("stop", "status", "uninstall"):
        assert parser.parse_args([name]).command == name
    with pytest.raises(SystemExit):
        parser.parse_args([])


# --- 버전·데이터 폴더·다른 설치본 ---


def test_version_flag_prints_the_version(capsys) -> None:
    with pytest.raises(SystemExit) as stopped:
        build_parser().parse_args(["--version"])

    assert stopped.value.code == 0
    assert "whatever.log" in capsys.readouterr().out


def test_status_shows_the_version_and_where_data_lives(tmp_path) -> None:
    lines: list[str] = []
    with (
        patch("launcher.commands.components.state", return_value=components.STOPPED),
        patch("launcher.commands.components.running_pids", return_value=[]),
        patch("launcher.commands.run_key.is_enabled", return_value=False),
        patch("launcher.commands.paths.data_dir", return_value=tmp_path),
    ):
        commands.status(lines.append)

    assert any(line.startswith("버전: ") for line in lines)
    assert any(line == f"데이터 폴더: {tmp_path}" for line in lines)


_OLD_SCRIPTS = Path("C:/old-folder/.venv/Scripts")


def _install_over(previous: str, *, stop_result=components.StopResult(2, ()), dry_run: bool = False):
    """다른 폴더의 설치가 `previous` 명령으로 등록된 상태에서 install하고 (성공 여부, 출력 줄, components.stop mock, 순서)를 돌려준다."""
    lines: list[str] = []
    order: list[str] = []
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.shortcuts.create", return_value=Path("x.lnk")),
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch(
            "launcher.commands.components.start", side_effect=lambda component: order.append("start") or components.STARTED
        ),
        patch(
            "launcher.commands.components.stop", side_effect=lambda component, **_: order.append("stop") or stop_result
        ) as stop,
        patch("launcher.commands.ui_build.is_built", return_value=True),
    ):
        run_key.registered_command.return_value = previous
        ok = commands.install(lines.append, dry_run=dry_run)
    return ok, lines, stop, order


def test_install_takes_over_another_folders_registration_and_stops_its_programs() -> None:
    """새 버전을 새 폴더에 풀어 install하면, 이전 폴더의 프로그램을 끄고 나서 이 폴더의 것을 띄운다 — 사용자가 이전 폴더에서
    직접 stop하지 않아도 된다(떠 있으면 같은 데이터의 lock 때문에 새 프로그램이 시작하지 못한다)."""
    ok, lines, stop, order = _install_over(f"{_OLD_SCRIPTS}\\pythonw.exe -m recorder.supervisor")

    assert ok is True
    assert [call.kwargs["scripts_dir"] for call in stop.call_args_list] == [_OLD_SCRIPTS.resolve()] * 2
    assert order == ["stop", "stop", "start", "start"]  # 끈 다음에 띄운다
    assert any("다른 폴더의 설치" in line and "이 폴더로 바꿉니다" in line for line in lines)
    assert any("이전 폴더에서 실행 중이던 것을 껐어요" in line for line in lines)
    assert not any("whatever-log stop" in line for line in lines)  # 사용자에게 시킬 일이 없다


def test_install_reports_previous_programs_it_could_not_stop() -> None:
    ok, lines, _, _ = _install_over(
        f"{_OLD_SCRIPTS}\\pythonw.exe -m recorder.supervisor", stop_result=components.StopResult(0, (42,))
    )

    assert ok is False and any(line.startswith("문제: ") and "42" in line for line in lines)


def test_a_dry_install_over_another_folder_stops_nothing() -> None:
    ok, lines, stop, _ = _install_over(f"{_OLD_SCRIPTS}\\pythonw.exe -m recorder.supervisor", dry_run=True)

    assert ok is True
    stop.assert_not_called()
    assert any("[미리보기]" in line and "끕니다" in line for line in lines)


def test_install_stops_nothing_when_the_registration_is_this_environments_with_other_arguments() -> None:
    """같은 가상환경의 등록이면(인자만 다름) 끌 "이전 설치본"이 없다 — 이 설치본의 프로그램은 start가 다룬다."""
    ok, _, stop, _ = _install_over(RECORDER.autostart_command() + " --interval 30")

    assert ok is True
    stop.assert_not_called()


def test_install_is_quiet_when_the_registration_is_already_this_folders() -> None:
    lines: list[str] = []
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.shortcuts.create", return_value=Path("x.lnk")),
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.components.start", return_value=components.STARTED),
        patch("launcher.commands.ui_build.is_built", return_value=True),
    ):
        run_key.registered_command.side_effect = lambda name: {RECORDER.run_key_value: RECORDER, SYNC.run_key_value: SYNC}[name].autostart_command()
        commands.install(lines.append)

    assert not any("다른 폴더의 설치" in line for line in lines)


def test_powershell_is_run_from_the_system_folder_not_found_by_name() -> None:
    """이름만 주면 현재 폴더·PATH의 다른 powershell.exe가 대신 실행될 수 있다."""
    path = Path(shortcuts.powershell_path())

    assert path.is_absolute() and path.is_file()
    assert path.parent.parent.parent == shortcuts.system_directory()


def test_the_system_folder_comes_from_the_windows_api_not_from_environment_or_a_fixed_drive(monkeypatch) -> None:
    """SystemRoot 환경변수는 지워지거나 바뀔 수 있고, 윈도우가 D:에 설치된 PC도 있다 — C:\\Windows를 가정하지 않는다."""
    real = shortcuts.system_directory()
    monkeypatch.delenv("SystemRoot", raising=False)
    monkeypatch.setenv("windir", r"X:\fake")

    assert shortcuts.system_directory() == real  # 환경변수가 없거나 틀려도 같다
    assert str(real).lower().endswith("system32")


def test_powershell_does_not_depend_on_the_environment_or_a_fixed_drive(monkeypatch) -> None:
    """환경변수가 가리키는 곳(D:\\Win 같은)이 아니라 윈도우가 알려 주는 실제 시스템 폴더의 PowerShell을 쓴다."""
    real = shortcuts.powershell_path()
    monkeypatch.setenv("SystemRoot", "D:\\Win")
    monkeypatch.setenv("windir", "D:\\Win")

    assert shortcuts.powershell_path() == real
    monkeypatch.delenv("SystemRoot")
    monkeypatch.delenv("windir")
    assert shortcuts.powershell_path() == real


def test_the_windows_api_failing_is_reported_not_guessed(monkeypatch) -> None:
    class Kernel32:
        def GetSystemDirectoryW(self, buffer, size):
            return 0  # 실패

    monkeypatch.setattr(shortcuts.ctypes, "windll", type("W", (), {"kernel32": Kernel32()})())

    with pytest.raises(OSError, match="시스템 폴더"):
        shortcuts.system_directory()


def test_the_child_environment_gets_system_root_back_when_it_is_missing(monkeypatch) -> None:
    """PowerShell·COM은 SystemRoot가 없으면 시작하지 못한다 — 지워진 환경에서도 바로가기를 만들 수 있게 채워 준다."""
    monkeypatch.delenv("SystemRoot", raising=False)

    env = shortcuts.powershell_env(WL_LINK="x.lnk")

    assert env["WL_LINK"] == "x.lnk"
    assert Path(env["SystemRoot"]) == shortcuts.system_directory().parent


def test_an_existing_system_root_is_left_alone(monkeypatch) -> None:
    monkeypatch.setenv("SystemRoot", r"D:\Windows")

    env = shortcuts.powershell_env()

    assert [value for name, value in env.items() if name.upper() == "SYSTEMROOT"] == [r"D:\Windows"]  # 대소문자만 다른 중복 없이


def test_a_shortcut_can_be_made_even_without_system_root_in_the_environment(tmp_path, monkeypatch) -> None:
    """지워진 환경(작업 스케줄러 등)에서도 실제로 만들어지고 읽혀야 한다."""
    monkeypatch.delenv("SystemRoot", raising=False)

    link = shortcuts.create(tmp_path)

    assert link.is_file() and shortcuts.is_ours(link)


# --- 안내 문구: 번들과 개발용 저장소가 서로 다른 명령·로그 위치를 말한다 ---


def test_the_recovery_hint_names_the_command_the_user_actually_has(tmp_path) -> None:
    lines: list[str] = []
    with (
        patch("launcher.commands.components.start", return_value=components.SUPERVISED),
        patch("launcher.commands.ui_build.is_built", return_value=False),
        patch("launcher.commands.paths.bundle_info", return_value={"version": "1"}),
        patch("launcher.commands._show_message"),
    ):
        commands.start(lines.append)
    assert any("whatever-log.cmd install" in line for line in lines)  # 번들에는 uv가 없다

    lines.clear()
    with (
        patch("launcher.commands.components.start", return_value=components.SUPERVISED),
        patch("launcher.commands.ui_build.is_built", return_value=False),
        patch("launcher.commands.paths.bundle_info", return_value=None),
        patch("launcher.commands._show_message"),
    ):
        commands.start(lines.append)
    assert any("uv run whatever-log install" in line for line in lines)


def test_the_window_error_points_at_the_log_in_the_data_folder_for_a_bundle(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WHATEVER_LOG_DATA_DIR", str(tmp_path))
    lines: list[str] = []
    with (
        patch("launcher.commands.components.start", return_value=components.SUPERVISED),
        patch("launcher.commands.ui_build.is_built", return_value=True),
        patch("launcher.commands.subprocess.run", return_value=MagicMock(returncode=3)),
        patch("launcher.commands._show_message"),
    ):
        commands.start(lines.append)

    assert any(str(tmp_path / "logs" / "hub-supervisor.log") in line for line in lines)  # 데이터 폴더의 logs/ (개발용 저장소의 apps/desktop/가 아니다)
