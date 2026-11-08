import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("build_release", Path(__file__).resolve().parents[1] / "build_release.py")
build_release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_release)


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """번들에 들어가야 할 것과 들어가면 안 되는 것이 섞인 작은 저장소."""
    root = tmp_path / "repo"
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE"):
        _write(root / name)
    _write(root / "VERSION", "1.0.0-beta.1\n")
    _write(root / ".python-version", "3.14\n")
    for app in build_release.PYTHON_APPS:
        _write(root / "apps" / app / "pyproject.toml")
        _write(root / "apps" / app / "src" / app / "__init__.py")
        _write(root / "apps" / app / "src" / app / "__pycache__" / "x.pyc")
        _write(root / "apps" / app / "tests" / "test_x.py")
        _write(root / "apps" / app / f"{app}.db")  # 실행하면 생기는 데이터
    for package in ("common", "cloud"):
        _write(root / "packages" / package / "pyproject.toml")
        _write(root / "packages" / package / "src" / package / "__init__.py")
        _write(root / "packages" / package / "tests" / "test_y.py")
    _write(root / "packages" / "notes" / "README.md")  # pyproject.toml이 없는 폴더는 패키지가 아니다
    _write(root / "apps" / "server" / "src" / "index.ts")  # Cloudflare 서버
    _write(root / "apps" / "server" / "wrangler.toml")
    _write(root / "apps" / "ui" / "src" / "main.ts")
    _write(root / "apps" / "ui" / "package.json")
    _write(root / "apps" / "ui" / "dist" / "index.html", "<html></html>")
    _write(root / "docs" / "a.md")
    _write(root / "Dockerfile")
    return root


def _staged(repo, tmp_path):
    target = tmp_path / "stage"
    build_release.stage("1.0.0-beta.1", target, repo)
    return target, {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}


# --- 버전 ---


@pytest.mark.parametrize("version", ["1.0.0", "0.1.0", "1.0.0-beta.1", "2.3.4-rc.2", "1.0.0-alpha"])
def test_semver_versions_are_accepted(repo, version) -> None:
    _write(repo / "VERSION", version + "\n")

    assert build_release.read_version(repo) == version


@pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0-", "01.0.0", "1.0.0 beta", "1.0.0-beta..1", ""])
def test_anything_else_is_rejected(repo, version) -> None:
    _write(repo / "VERSION", version + "\n")

    with pytest.raises(ValueError):
        build_release.read_version(repo)


@pytest.mark.parametrize(
    ("version", "channel"), [("1.0.0", "stable"), ("1.0.0-beta.1", "beta"), ("2.0.0-rc.3", "rc"), ("1.0.0-alpha", "alpha")]
)
def test_the_channel_is_stable_or_the_prerelease_name(version, channel) -> None:
    assert build_release.channel_of(version) == channel


def test_the_shipped_version_file_is_valid() -> None:
    assert build_release.read_version()  # 저장소의 VERSION이 SemVer가 아니면 릴리스를 만들 수 없다


def test_the_pinned_python_matches_what_ci_and_the_release_build_use() -> None:
    """번들 설치(uv sync)가 고르는 파이썬이 CI·릴리스 빌드가 시험한 버전과 같아야 한다."""
    root = Path(__file__).resolve().parents[2]
    pinned = (root / ".python-version").read_text(encoding="utf-8").strip()
    workflows = root / ".github" / "workflows"

    for workflow in sorted(workflows.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if "uv python install" in text:
            assert f"uv python install {pinned}" in text, workflow.name


# --- 번들 내용 ---


def test_the_bundle_has_what_a_users_pc_needs(repo, tmp_path) -> None:
    _, files = _staged(repo, tmp_path)

    assert {"pyproject.toml", "uv.lock", "VERSION", "README.md", "LICENSE", "install.cmd", "release.json"} <= files
    assert ".python-version" in files  # 없으면 사용자 PC의 uv가 CI와 다른(더 새) 파이썬을 고른다
    assert "apps/launcher/pyproject.toml" in files and "apps/launcher/src/launcher/__init__.py" in files
    assert "packages/common/src/common/__init__.py" in files
    assert "apps/ui/dist/index.html" in files


def test_the_bundle_leaves_out_the_server_the_ui_sources_tests_docs_and_local_data(repo, tmp_path) -> None:
    _, files = _staged(repo, tmp_path)

    assert not any(name.startswith("apps/server") for name in files)  # Cloudflare 서버는 사용자 PC에서 쓰지 않는다
    assert "apps/ui/src/main.ts" not in files and "apps/ui/package.json" not in files
    assert not any("/tests/" in name for name in files)
    assert not any(name.startswith("docs/") for name in files) and "Dockerfile" not in files
    assert not any(name.endswith(".db") or name.endswith(".pyc") or "__pycache__" in name for name in files)
    assert "packages/notes/README.md" not in files


def test_the_install_script_ships_with_crlf_line_endings(repo, tmp_path, monkeypatch) -> None:
    """원본이 LF여도 번들의 install.cmd는 CRLF여야 한다 — cmd는 LF 배치 파일을 실행하다 구문 오류로 멈춘다."""
    script = tmp_path / "install.cmd"
    script.write_bytes("@echo off\nif errorlevel 1 (\n  echo 한글\n)\r\n".encode())
    monkeypatch.setattr(build_release, "INSTALL_SCRIPT", script)

    target, _ = _staged(repo, tmp_path)
    shipped = (target / "install.cmd").read_bytes()

    assert shipped == "@echo off\r\nif errorlevel 1 (\r\n  echo 한글\r\n)\r\n".encode()


def test_the_real_install_script_ships_with_only_crlf(repo, tmp_path) -> None:
    target, _ = _staged(repo, tmp_path)
    shipped = (target / "install.cmd").read_bytes()

    assert shipped.count(b"\n") == shipped.count(b"\r\n") > 0


def test_the_marker_records_the_version_and_channel(repo, tmp_path) -> None:
    target, _ = _staged(repo, tmp_path)

    assert json.loads((target / "release.json").read_text(encoding="utf-8")) == {"version": "1.0.0-beta.1", "channel": "beta"}


def test_staging_without_a_built_ui_fails_with_a_hint(repo, tmp_path) -> None:
    (repo / "apps" / "ui" / "dist" / "index.html").unlink()

    with pytest.raises(SystemExit, match="화면"):
        build_release.stage("1.0.0", tmp_path / "stage", repo)


# --- zip ---


def test_the_zip_has_one_top_folder_and_is_reproducible(repo, tmp_path) -> None:
    target, _ = _staged(repo, tmp_path)
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"

    build_release.make_zip(target, first)
    build_release.make_zip(target, second)

    names = zipfile.ZipFile(first).namelist()
    assert {name.split("/")[0] for name in names} == {"stage"}
    assert build_release.sha256(first) == build_release.sha256(second)  # 같은 내용이면 같은 파일(해시로 확인할 수 있게)


# --- 명령줄 ---


def test_a_tag_that_differs_from_the_version_stops_the_release(monkeypatch, capsys) -> None:
    monkeypatch.setattr(build_release, "read_version", lambda: "1.0.0-beta.1")

    assert build_release.main(["--skip-ui-build", "--expect-tag", "v1.0.0"]) == 1
    assert "VERSION" in capsys.readouterr().err


def test_ui_build_output_goes_to_stderr_so_stdout_only_carries_the_result(monkeypatch, repo) -> None:
    """워크플로가 표준 출력의 zip 경로 줄을 읽는다 — pnpm의 진행 출력이 섞이면 엉뚱한 파일을 올린다."""
    calls = []
    monkeypatch.setattr(build_release.shutil, "which", lambda name: "corepack")
    monkeypatch.setattr(build_release.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))

    build_release.build_ui(repo)

    assert len(calls) == 2
    for _, kwargs in calls:
        assert kwargs["stdout"] is build_release.sys.stderr and kwargs["check"] is True


def test_the_workflow_picks_the_zip_line_not_the_first_line() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "head -n1" not in workflow and "grep '\.zip$'" in workflow
