import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location("build_release", Path(__file__).resolve().parents[1] / "build_release.py")
build_release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_release)

# 아래 autouse 픽스처가 가짜로 바꾸기 전의 진짜 함수들(내려받기·해시 확인은 따로 시험한다)
_REAL_FETCH = build_release.fetch_embedded_python
_REAL_EXPORT = build_release.export_requirements
_REAL_INSTALL = build_release.install_dependencies

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"


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
    _write(root / ".mise.toml", '[tools]\nnode = "24.22.1"\npython = "3.14.8"\n')
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


def _fake_embedded_zip(path: Path) -> Path:
    """임베더블 파이썬 zip을 흉내 낸 작은 zip(진짜는 12MB). 이름과 구조만 같다."""
    with zipfile.ZipFile(path, "w") as bundle:
        for name in ("python.exe", "pythonw.exe", "python314.dll", "python3.dll", "python314.zip", "LICENSE.txt"):
            bundle.writestr(name, f"fake {name}")
        bundle.writestr("python314._pth", "python314.zip\r\n.\r\n#import site\r\n")
    return path


@pytest.fixture(autouse=True)
def _no_network_no_uv(monkeypatch, tmp_path):
    """임베더블 zip 내려받기와 uv 호출은 가짜로 바꾼다(각 단계는 따로 시험한다)."""
    zip_path = _fake_embedded_zip(tmp_path / "embed.zip")
    monkeypatch.setattr(build_release, "fetch_embedded_python", lambda version, cache_dir: zip_path)
    monkeypatch.setattr(build_release, "export_requirements", lambda root, output: output.write_text("psutil==1\n", encoding="utf-8"))

    def fake_install(requirements, target, python):
        _write(target / "psutil" / "__init__.py")
        _write(target / "bin" / "keyring.exe")  # 빌드 PC의 경로가 박힌 명령 실행기

    monkeypatch.setattr(build_release, "install_dependencies", fake_install)


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


def test_the_ci_python_matches_the_pin() -> None:
    """번들을 만드는 uv가 쓰는 파이썬(CI)과 .python-version이 같아야 한다."""
    root = Path(__file__).resolve().parents[2]
    pinned = (root / ".python-version").read_text(encoding="utf-8").strip()

    for workflow in sorted((root / ".github" / "workflows").glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if "uv python install" in text:
            assert f"uv python install {pinned}" in text, workflow.name


# --- 번들 내용 ---


def test_the_bundle_has_what_a_users_pc_needs(repo, tmp_path) -> None:
    _, files = _staged(repo, tmp_path)

    assert {"VERSION", "README.md", "LICENSE", "install.cmd", "whatever-log.cmd", "release.json"} <= files
    assert "apps/launcher/src/launcher/__init__.py" in files and "packages/common/src/common/__init__.py" in files
    assert "apps/ui/dist/index.html" in files
    assert {"runtime/whatever-log.exe", "runtime/whatever-log-cli.exe", "runtime/python314.dll", "runtime/python314._pth"} <= files
    assert "runtime/Lib/site-packages/psutil/__init__.py" in files


def test_the_bundle_does_not_need_uv_or_a_python_on_the_users_pc(repo, tmp_path) -> None:
    """설치는 번들 안의 실행 파일로 한다 — uv.lock·pyproject.toml·.python-version은 더 이상 쓰이지 않는다."""
    target, files = _staged(repo, tmp_path)

    assert not ({"uv.lock", "pyproject.toml", ".python-version"} & files)
    assert not any(name.endswith("pyproject.toml") for name in files)
    for script in ("install.cmd", "whatever-log.cmd"):
        text = (target / script).read_text(encoding="utf-8")
        assert "runtime\\whatever-log-cli.exe" in text
        assert "uv " not in text and "uv.exe" not in text and "winget" not in text


def test_the_bundle_leaves_out_the_server_the_ui_sources_tests_docs_and_local_data(repo, tmp_path) -> None:
    _, files = _staged(repo, tmp_path)

    assert not any(name.startswith("apps/server") for name in files)  # Cloudflare 서버는 사용자 PC에서 쓰지 않는다
    assert "apps/ui/src/main.ts" not in files and "apps/ui/package.json" not in files
    assert not any("/tests/" in name for name in files)
    assert not any(name.startswith("docs/") for name in files) and "Dockerfile" not in files
    assert not any(name.endswith(".db") or name.endswith(".pyc") or "__pycache__" in name for name in files)
    assert "packages/notes/README.md" not in files


def test_the_install_scripts_ship_with_crlf_line_endings(repo, tmp_path, monkeypatch) -> None:
    """원본이 LF여도 번들의 .cmd는 CRLF여야 한다 — cmd는 LF 배치 파일을 실행하다 구문 오류로 멈춘다."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "install.cmd").write_bytes("@echo off\nif errorlevel 1 (\n  echo 한글\n)\r\n".encode())
    (scripts / "whatever-log.cmd").write_bytes(b"@echo off\nexit /b 0\n")
    monkeypatch.setattr(build_release, "RELEASE_DIR", scripts)

    target, _ = _staged(repo, tmp_path)

    assert (target / "install.cmd").read_bytes() == "@echo off\r\nif errorlevel 1 (\r\n  echo 한글\r\n)\r\n".encode()
    assert (target / "whatever-log.cmd").read_bytes() == b"@echo off\r\nexit /b 0\r\n"


def test_the_real_scripts_ship_with_only_crlf(repo, tmp_path) -> None:
    target, _ = _staged(repo, tmp_path)

    for script in ("install.cmd", "whatever-log.cmd"):
        shipped = (target / script).read_bytes()
        assert shipped.count(b"\n") == shipped.count(b"\r\n") > 0


def test_the_marker_records_the_version_and_channel(repo, tmp_path) -> None:
    target, _ = _staged(repo, tmp_path)

    assert json.loads((target / "release.json").read_text(encoding="utf-8")) == {"version": "1.0.0-beta.1", "channel": "beta"}


def test_staging_without_a_built_ui_fails_with_a_hint(repo, tmp_path) -> None:
    (repo / "apps" / "ui" / "dist" / "index.html").unlink()

    with pytest.raises(SystemExit, match="화면"):
        build_release.stage("1.0.0", tmp_path / "stage", repo)


# --- 런타임(임베더블 파이썬) ---


def test_the_executables_are_renamed_so_the_window_owner_is_the_app_name(repo, tmp_path) -> None:
    """recorder는 창을 가진 프로세스의 실행 파일 이름을 기록한다 — pythonw.exe면 다른 파이썬 프로그램과 구분되지 않는다."""
    target, files = _staged(repo, tmp_path)

    assert (target / "runtime" / "whatever-log.exe").read_text() == "fake pythonw.exe"  # 콘솔 없는 쪽
    assert (target / "runtime" / "whatever-log-cli.exe").read_text() == "fake python.exe"  # 콘솔 있는 쪽
    assert "runtime/python.exe" not in files and "runtime/pythonw.exe" not in files  # 원래 이름은 남기지 않는다


def test_the_path_file_is_named_after_the_versioned_dll_and_lists_relative_source_folders(repo, tmp_path) -> None:
    target, files = _staged(repo, tmp_path)

    assert "runtime/python314._pth" in files and "runtime/python3._pth" not in files  # python3.dll이 아니라 python314.dll 기준
    lines = (target / "runtime" / "python314._pth").read_bytes().decode("utf-8").split("\r\n")
    assert lines[:3] == ["python314.zip", ".", "Lib\\site-packages"]
    assert lines[-2:] == ["import site", ""]
    assert "..\\apps\\launcher\\src" in lines and "..\\packages\\common\\src" in lines
    assert not any(line.startswith("..\\apps\\server") for line in lines)  # 서버는 번들에 없다
    for line in lines:
        if line.startswith("..\\"):
            assert (target / "runtime" / line.replace("\\", "/")).resolve().is_dir(), line  # 가리키는 폴더가 번들에 실제로 있다


def test_machine_specific_command_launchers_are_removed(repo, tmp_path) -> None:
    """의존성 설치가 만든 bin\\keyring.exe 같은 실행기에는 빌드 PC의 파이썬 경로가 박혀 있다."""
    _, files = _staged(repo, tmp_path)

    assert not any(name.startswith("runtime/Lib/site-packages/bin") for name in files)


def test_the_temporary_requirements_file_is_not_shipped(repo, tmp_path) -> None:
    _, files = _staged(repo, tmp_path)

    assert not any(name.endswith("requirements.txt") for name in files)


def test_dependencies_are_installed_for_the_target_platform_not_this_machine(tmp_path, monkeypatch) -> None:
    """이 PC의 파이썬이 아니라 번들에 넣을 Windows·파이썬 버전용으로 받는다(빌드 PC가 달라도 같은 결과)."""
    seen = {}
    monkeypatch.setattr(build_release.subprocess, "run", lambda command, **kwargs: seen.update(command=command, kwargs=kwargs))

    _REAL_INSTALL(tmp_path / "req.txt", tmp_path / "site", "3.14.8")

    command = seen["command"]
    assert command[:3] == ["uv", "pip", "install"]
    assert command[command.index("--python-platform") + 1] == "windows"
    assert command[command.index("--python-version") + 1] == "3.14.8"
    assert seen["kwargs"]["check"] is True and seen["kwargs"]["stdout"] is build_release.sys.stderr


def test_requirements_come_from_the_lock_without_dev_or_workspace_packages(tmp_path, monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(build_release.subprocess, "run", lambda command, **kwargs: seen.update(command=command))

    _REAL_EXPORT(tmp_path, tmp_path / "req.txt")

    command = seen["command"]
    assert {"--frozen", "--no-dev", "--all-packages", "--no-emit-workspace"} <= set(command)  # uv.lock 그대로, 개발용·우리 패키지 제외


# --- 파이썬 버전과 무결성 ---


def test_the_python_version_comes_from_mise_toml_and_must_be_exact(repo) -> None:
    assert build_release.python_version(repo) == "3.14.8"
    _write(repo / ".mise.toml", '[tools]\npython = "3.14"\n')

    with pytest.raises(ValueError, match="정확한 버전"):
        build_release.python_version(repo)


def test_the_shipped_python_version_has_a_pinned_hash() -> None:
    """.mise.toml의 python을 올리면서 EMBEDDED_PYTHON_SHA256을 안 바꾸면, 번들을 만들 수 없어야 한다(조용히 다른 파이썬이 들어가지 않게)."""
    version = build_release.python_version()

    assert version in build_release.EMBEDDED_PYTHON_SHA256
    assert re.fullmatch(r"[0-9a-f]{64}", build_release.EMBEDDED_PYTHON_SHA256[version])


def test_an_unknown_python_version_stops_the_build_with_a_hint(tmp_path) -> None:
    with pytest.raises(SystemExit, match="EMBEDDED_PYTHON_SHA256"):
        _REAL_FETCH("3.99.0", tmp_path)


def test_a_download_with_the_wrong_hash_is_rejected_and_discarded(tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(build_release.EMBEDDED_PYTHON_SHA256, "9.9.9", "0" * 64)
    monkeypatch.setattr(build_release.urllib.request, "urlretrieve", lambda url, path: Path(path).write_bytes(b"tampered"))

    with pytest.raises(SystemExit, match="SHA-256이 달라요"):
        _REAL_FETCH("9.9.9", tmp_path)

    assert not (tmp_path / "python-9.9.9-embed-amd64.zip").exists()  # 잘못된 파일을 캐시에 남기지 않는다


def test_a_cached_download_with_the_right_hash_is_reused_without_downloading(tmp_path, monkeypatch) -> None:
    content = b"genuine"
    monkeypatch.setitem(build_release.EMBEDDED_PYTHON_SHA256, "9.9.9", hashlib.sha256(content).hexdigest())
    (tmp_path / "python-9.9.9-embed-amd64.zip").write_bytes(content)

    def forbidden(url, path):
        raise AssertionError("이미 받은 파일을 다시 내려받았다")

    monkeypatch.setattr(build_release.urllib.request, "urlretrieve", forbidden)

    assert _REAL_FETCH("9.9.9", tmp_path).read_bytes() == content


def test_a_corrupted_cache_is_downloaded_again(tmp_path, monkeypatch) -> None:
    content = b"genuine"
    monkeypatch.setitem(build_release.EMBEDDED_PYTHON_SHA256, "9.9.9", hashlib.sha256(content).hexdigest())
    (tmp_path / "python-9.9.9-embed-amd64.zip").write_bytes(b"half-written")
    monkeypatch.setattr(build_release.urllib.request, "urlretrieve", lambda url, path: Path(path).write_bytes(content))

    assert _REAL_FETCH("9.9.9", tmp_path).read_bytes() == content


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


# --- 워크플로 ---


def test_the_workflow_installs_the_bundle_before_publishing_it() -> None:
    """만든 zip을 install.cmd로 설치해 본 뒤에만 Release를 올린다 — v1.0.0-beta.1은 설치되지 않는 채로 나갔다."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    install = workflow.index("call install.cmd")
    publish = workflow.index("gh release create")
    assert install < publish
    assert "shell: cmd" in workflow[:install]  # 사용자가 더블클릭하는 것과 같게 cmd로 실행한다


def test_the_workflow_installs_without_uv_or_python_on_the_path() -> None:
    """번들이 uv·파이썬에 기대지 않는다는 것을 설치 시험이 보장해야 한다 — 러너에는 둘 다 깔려 있어서, PATH를 비워야 의존 여부가 드러난다."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    install_step = workflow[workflow.index("call install.cmd") - 400 : workflow.index("call install.cmd")]

    assert "set PATH=%SystemRoot%\\System32" in install_step
    after = workflow[workflow.index("call install.cmd") :]
    assert "uv run" not in after.split("GitHub Release 올리기")[0]  # 설치 시험 구간은 uv를 부르지 않는다


def test_a_manual_run_of_the_workflow_does_not_publish() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    publish_step = workflow[workflow.index("- name: GitHub Release 올리기") :]

    assert "workflow_dispatch:" in workflow
    assert "if: github.ref_type == 'tag'" in publish_step.split("run:")[0]


def test_the_workflow_picks_the_zip_line_not_the_first_line() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "head -n1" not in workflow and r"grep '\.zip$'" in workflow


def test_the_release_notes_do_not_ask_for_uv() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "uv 필요" not in workflow
