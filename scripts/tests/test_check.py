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


# --- 리뷰 반영: 이름 정규화, biome 설정, 선택기 시험, git 경로, Biome 옵션, 실행 실패 ---


def test_dependency_names_are_compared_after_normalizing(tmp_path) -> None:
    """의존성에 `Common`·`my_pkg`처럼 적어도 프로젝트 이름(`common`·`my-pkg`)과 같은 것으로 읽어야 한다 — 아니면 의존 관계가 누락되어 테스트가 빠진다."""
    root = tmp_path / "repo"
    _write(root / "pyproject.toml", '[tool.uv.workspace]\nmembers = ["packages/common", "packages/my_pkg", "apps/hub"]\n')
    _project(root, "packages/common", "common")
    _project(root, "packages/my_pkg", "my_pkg", "COMMON")
    _project(root, "apps/hub", "hub", "My.Pkg>=1")
    _write(root / "packages" / "common" / "src" / "common" / "x.py")

    planned = check.plan(["packages/common/src/common/x.py"], root)

    assert {"packages/my_pkg/tests", "apps/hub/tests"} <= set(planned.pytest)  # 대소문자·밑줄·점이 달라도 건너서 이어진다


def test_a_biome_config_change_lints_the_whole_repo(repo) -> None:
    """규칙이 바뀌면 건드리지 않은 파일도 새 규칙에 걸릴 수 있다 — 바뀐 파일만 검사하면 머지 뒤 전체 lint가 깨진다."""
    _write(repo / "biome.json")

    planned = check.plan(["biome.json"], repo)

    assert planned.lint == []  # 빈 목록은 저장소 전체
    assert planned.node == list(check.NODE_CHECKS)


@pytest.mark.parametrize("member", ["apps/hub", "packages/common"])
def test_a_member_dependency_change_also_runs_the_selector_tests(repo, member) -> None:
    """`apps/hub/pyproject.toml`에서 cloud만 빼도, 의존 관계를 읽는 선택기의 시험이 돌아야 한다."""
    _write(repo / "scripts" / "tests" / "test_check.py")

    planned = check.plan([f"{member}/pyproject.toml"], repo)

    assert check.SELECTOR_TEST in planned.pytest


def test_a_source_change_does_not_need_the_selector_tests(repo) -> None:
    _write(repo / "scripts" / "tests" / "test_check.py")

    assert check.SELECTOR_TEST not in check.plan(["apps/hub/src/hub/api.py"], repo).pytest


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """커밋이 하나 있는 실제 git 저장소(main 브랜치)."""
    root = tmp_path / "gitrepo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root / "packages" / "common" / "src" / "common" / "paths.py", "a" * 200 + "\n")
    _write(root / "README.md")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "feature")
    return root


def test_non_ascii_paths_are_read_as_they_are(git_repo) -> None:
    """git 기본 출력은 한글 경로를 "\354..." 같은 따옴표 이스케이프로 바꿔서, 실제로는 없는 경로로 읽혀 검사에서 빠진다."""
    path = "apps/ui/src/설정.ts"
    _write(git_repo / path)
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "한글 파일")

    assert check.changed_files("main", git_repo) == [path]


def test_uncommitted_and_untracked_non_ascii_paths_are_read_too(git_repo) -> None:
    _write(git_repo / "docs" / "메모.md")  # 아직 git이 모르는 새 파일
    (git_repo / "README.md").write_text("바뀜", encoding="utf-8")  # 커밋 안 한 변경

    assert check.changed_files("main", git_repo) == ["README.md", "docs/메모.md"]


def test_a_moved_file_reports_both_the_old_and_the_new_path(git_repo) -> None:
    """옮긴 파일을 새 경로 하나로 합쳐 보여 주면, 이전 경로(packages/common)의 테스트가 돌지 않는다."""
    (git_repo / "docs").mkdir()
    _git(git_repo, "mv", "packages/common/src/common/paths.py", "docs/paths.py")
    _git(git_repo, "commit", "-q", "-m", "옮김")

    changed = check.changed_files("main", git_repo)

    assert "packages/common/src/common/paths.py" in changed and "docs/paths.py" in changed


def test_biome_gets_the_paths_after_a_double_dash(repo) -> None:
    """`--help`라는 파일이 같이 바뀌면 Biome가 그것을 옵션으로 읽어, 파일을 검사하지 않고 도움말만 출력한 뒤 성공한다."""
    steps = dict(check.commands(check.Plan(lint=["--help", "apps/ui/src/main.ts"])))

    command = steps["Biome"]
    assert command[command.index("--") + 1 :] == ["--help", "apps/ui/src/main.ts"]


def test_a_check_that_cannot_start_is_a_failure_but_the_rest_still_run(monkeypatch, capsys) -> None:
    calls = []

    def fake_run(command, cwd=None):
        calls.append(command[0])
        if "corepack" in str(command[0]):
            raise FileNotFoundError("corepack을 찾을 수 없어요")
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(check.subprocess, "run", fake_run)
    monkeypatch.setattr(check, "changed_files", lambda base: ["apps/ui/src/main.ts"])
    monkeypatch.setattr(check, "commands", lambda planned, only=None: [("Biome", ["corepack", "x"]), ("pytest", ["python", "-m", "pytest"])])

    exit_code = check.main([])

    assert exit_code == 1
    assert calls == ["corepack", "python"]  # Biome를 못 띄워도 pytest는 돌았다
    out = capsys.readouterr()
    assert "실패: Biome" in out.out and "corepack" in out.err


def test_the_workflow_does_not_leave_the_token_in_the_checkout() -> None:
    """PR의 테스트 코드가 실행되는 동안 읽기 토큰이 .git 설정에 남아 있으면 외부로 보낼 수 있다."""
    workflow = (check.ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert workflow.count("actions/checkout@") == workflow.count("persist-credentials: false") == 2
