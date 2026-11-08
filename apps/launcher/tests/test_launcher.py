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


# --- 띄우고 끄기 ---


def test_start_does_nothing_when_the_component_is_already_running() -> None:
    with patch("launcher.components.running_pids", return_value=[7]), patch("launcher.components.subprocess.Popen") as popen:
        assert components.start(RECORDER) is False

    popen.assert_not_called()


def test_start_launches_the_supervisor_detached_without_a_console() -> None:
    with patch("launcher.components.running_pids", return_value=[]), patch("launcher.components.subprocess.Popen") as popen:
        assert components.start(SYNC) is True

    command = popen.call_args.args[0]
    assert command[1:] == ["-m", "sync_agent.supervisor"] and command[0].endswith("pythonw.exe")
    flags = popen.call_args.kwargs["creationflags"]
    assert flags & subprocess.DETACHED_PROCESS and flags & subprocess.CREATE_NO_WINDOW
    assert popen.call_args.kwargs["cwd"] == components.REPO_ROOT


def test_stop_terminates_the_supervisor_before_the_program() -> None:
    order: list[str] = []

    def fake_find(module, **_):
        return [module]

    with (
        patch("launcher.components.find_processes", side_effect=fake_find),
        patch("launcher.components._terminate", side_effect=lambda items: order.extend(items)),
    ):
        count = components.stop(SYNC)

    assert order == ["sync_agent.supervisor", "sync_agent"]  # supervisor가 먼저여야 프로그램을 다시 띄우지 못한다
    assert count == 2


# --- 설치 ---


def _collect():
    lines: list[str] = []
    return lines, lines.append


def test_a_dry_run_changes_nothing() -> None:
    lines, say = _collect()
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.shortcuts.create") as create,
        patch("launcher.commands.components.start") as start,
        patch("launcher.commands.ui_build.build") as build,
        patch("launcher.commands.ui_build.is_built", return_value=False),
    ):
        assert commands.install(say, dry_run=True, desktop_shortcut=True) is True

    run_key.enable.assert_not_called()
    create.assert_not_called()
    start.assert_not_called()
    build.assert_not_called()
    assert any("바탕화면" in line for line in lines) and all("미리보기" in line or "끝났어요" in line for line in lines)


def test_install_registers_both_components_makes_the_shortcut_and_starts_them() -> None:
    lines, say = _collect()
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.shortcuts.create", return_value=Path("x.lnk")) as create,
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.components.start", return_value=True) as start,
        patch("launcher.commands.ui_build.is_built", return_value=True),
    ):
        assert commands.install(say) is True

    registered = [call.args[0] for call in run_key.enable.call_args_list]
    assert registered == [RECORDER.run_key_value, SYNC.run_key_value]
    assert run_key.enable.call_args_list[1].args[1].endswith("-m sync_agent.supervisor")
    create.assert_called_once_with(Path("menu"))
    assert start.call_count == 2


def test_one_failing_step_does_not_stop_the_rest_and_is_reported() -> None:
    lines, say = _collect()
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.shortcuts.create", return_value=Path("x.lnk")),
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.components.start", return_value=True) as start,
        patch("launcher.commands.ui_build.is_built", return_value=False),
        patch("launcher.commands.ui_build.build", side_effect=ui_build.UiBuildError("Node.js가 없어요")),
    ):
        ok = commands.install(say)

    assert ok is False
    assert run_key.enable.call_count == 2 and start.call_count == 2  # 화면 빌드가 실패해도 나머지는 했다
    assert any(line.startswith("문제: 화면 빌드") and "Node.js" in line for line in lines)


def test_install_can_skip_the_ui_build_and_the_start() -> None:
    lines, say = _collect()
    with (
        patch("launcher.commands.run_key"),
        patch("launcher.commands.shortcuts.create", return_value=Path("x.lnk")),
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.components.start") as start,
        patch("launcher.commands.ui_build.build") as build,
        patch("launcher.commands.ui_build.is_built", return_value=False),
    ):
        commands.install(say, build_ui=False, start_now=False)

    build.assert_not_called()
    start.assert_not_called()


def test_uninstall_stops_unregisters_and_keeps_the_data() -> None:
    lines, say = _collect()
    with (
        patch("launcher.commands.run_key") as run_key,
        patch("launcher.commands.components.stop", return_value=2) as stop,
        patch("launcher.commands.shortcuts.remove", return_value=True),
        patch("launcher.commands.shortcuts.start_menu_dir", return_value=Path("menu")),
        patch("launcher.commands.shortcuts.desktop_dir", return_value=Path("desk")),
    ):
        commands.uninstall(say)

    assert stop.call_count == 2
    assert [call.args[0] for call in run_key.disable.call_args_list] == [RECORDER.run_key_value, SYNC.run_key_value]
    assert any("지우지 않았어요" in line for line in lines)


def test_start_without_a_window_only_starts_the_components() -> None:
    with (
        patch("launcher.commands.components.start", return_value=False),
        patch("launcher.commands.subprocess.run") as run,
    ):
        commands.start(lambda _: None, open_window=False)

    run.assert_not_called()


def test_start_opens_the_desktop_window_with_pythonw() -> None:
    with (
        patch("launcher.commands.components.start", return_value=True),
        patch("launcher.commands.subprocess.run") as run,
    ):
        commands.start(lambda _: None)

    assert run.call_args.args[0][1:] == ["-m", "desktop"]


# --- 화면 빌드 ---


def test_ui_build_reports_missing_node_in_plain_words() -> None:
    with patch("launcher.ui_build.shutil.which", return_value=None):
        with pytest.raises(ui_build.UiBuildError, match="Node.js"):
            ui_build.build()


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
        env={**__import__("os").environ, "WL_LINK": str(link)},
        capture_output=True,
        text=True,
        check=True,
    )
    target, arguments, icon = result.stdout.strip().splitlines()
    assert target.endswith("pythonw.exe") and arguments == "-m launcher start"
    assert icon.endswith("icon.ico,0") and Path(icon.rsplit(",", 1)[0]).is_file()
    assert shortcuts.remove(tmp_path / "menu") is True and shortcuts.remove(tmp_path / "menu") is False


# --- 명령줄 ---


def test_every_documented_command_parses() -> None:
    parser = build_parser()

    assert parser.parse_args(["install", "--dry-run", "--desktop-shortcut", "--skip-ui-build", "--no-start"]).dry_run
    assert parser.parse_args(["start", "--no-window"]).no_window
    for name in ("stop", "status", "uninstall"):
        assert parser.parse_args([name]).command == name
    with pytest.raises(SystemExit):
        parser.parse_args([])
