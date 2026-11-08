import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("check", Path(__file__).resolve().parents[1] / "check.py")
check = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _project(root: Path, member: str, name: str, *dependencies: str) -> None:
    listed = ", ".join(f'"{dependency}"' for dependency in dependencies)
    _write(root / member / "pyproject.toml", f'[project]\nname = "{name}"\ndependencies = [{listed}]\n')
    _write(root / member / "tests" / "test_x.py")


@pytest.fixture
def repo(tmp_path):
    """common ← recorder ← hub, cloud ← hub 로 이어진 작은 워크스페이스."""
    root = tmp_path / "repo"
    members = ["packages/common", "packages/cloud", "apps/recorder", "apps/hub"]
    _write(root / "pyproject.toml", "[tool.uv.workspace]\nmembers = [" + ", ".join(f'"{m}"' for m in members) + "]\n")
    _project(root, "packages/common", "common")
    _project(root, "packages/cloud", "cloud", "keyring>=25.7.0")
    _project(root, "apps/recorder", "recorder", "psutil>=6.1.0", "common")
    _project(root, "apps/hub", "hub", "recorder", "cloud", "common")
    _write(root / "packages" / "cloud" / "tests" / "test_isolation.py")
    _write(root / "scripts" / "tests" / "test_build_release.py")
    for path in ("packages/common/src/common/paths.py", "apps/hub/src/hub/api.py", "apps/ui/src/main.ts", "docs/a.md"):
        _write(root / path)
    return root


def test_a_change_runs_the_tests_of_everything_that_depends_on_it(repo) -> None:
    planned = check.plan(["packages/common/src/common/paths.py"], repo)

    assert planned.pytest == [
        "apps/hub/tests",
        "apps/recorder/tests",
        "packages/cloud/tests/test_isolation.py",
        "packages/common/tests",
    ]
    assert planned.node == []


def test_a_change_at_the_top_runs_only_its_own_tests(repo) -> None:
    planned = check.plan(["apps/hub/src/hub/api.py"], repo)

    assert planned.pytest == ["apps/hub/tests", "packages/cloud/tests/test_isolation.py"]


def test_only_the_changed_files_are_linted(repo) -> None:
    planned = check.plan(["apps/hub/src/hub/api.py", "apps/hub/src/hub/deleted.py"], repo)

    assert planned.lint == ["apps/hub/src/hub/api.py"]  # 지운 파일은 검사할 수 없다


def test_a_ui_change_runs_the_ui_checks_and_no_python_tests(repo) -> None:
    planned = check.plan(["apps/ui/src/main.ts"], repo)

    assert planned.node == ["ui"]
    assert planned.pytest == []


def test_a_server_change_also_runs_the_test_that_executes_the_server_code(repo) -> None:
    _write(repo / "packages" / "goals" / "tests" / "test_name_key_parity.py")

    planned = check.plan(["apps/server/src/sync/goalInput.ts"], repo)

    assert planned.node == ["server"]
    assert planned.pytest == ["packages/goals/tests/test_name_key_parity.py"]


@pytest.mark.parametrize("path", ["scripts/build_release.py", ".github/workflows/release.yml", "VERSION"])
def test_release_files_run_the_release_tests(repo, path) -> None:
    assert check.plan([path], repo).pytest == ["scripts/tests"]


@pytest.mark.parametrize("path", ["uv.lock", "pyproject.toml", ".python-version"])
def test_root_python_settings_run_every_python_test(repo, path) -> None:
    assert check.plan([path], repo).pytest == ["."]


def test_root_node_settings_run_every_node_check(repo) -> None:
    assert check.plan(["pnpm-lock.yaml"], repo).node == list(check.NODE_CHECKS)


def test_a_docs_only_change_runs_nothing(repo) -> None:
    assert check.plan(["docs/gone.md"], repo).is_empty()


def test_everything_ignores_what_changed(repo) -> None:
    planned = check.plan([], repo, everything=True)

    assert planned.lint == [] and planned.pytest == ["."] and planned.node == list(check.NODE_CHECKS)


def test_only_python_leaves_out_biome_and_node(repo) -> None:
    steps = check.commands(check.plan(["apps/ui/src/main.ts", "apps/hub/src/hub/api.py"], repo), only="python")

    assert [label for label, _ in steps] == ["pytest"]


def test_running_everything_lints_and_tests_the_whole_repo(repo) -> None:
    steps = dict(check.commands(check.plan([], repo, everything=True)))

    assert steps["Biome"][-1] == "."
    assert steps["pytest"][-2:] == ["-c", str(check.ROOT / "pyproject.toml")]  # 경로를 주지 않으면 testpaths 전부


def test_the_real_workspace_is_read_with_its_dependencies() -> None:
    projects = check.python_projects()

    assert projects["hub"][0] == "apps/hub"
    assert {"recorder", "common", "cloud"} <= projects["hub"][1]
    assert "psutil" not in projects["recorder"][1]  # 워크스페이스 밖의 의존성은 빼고 본다


def test_ci_runs_the_same_script() -> None:
    workflow = (check.ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "scripts/check.py" in workflow and "--only python" in workflow and "--only node" in workflow
