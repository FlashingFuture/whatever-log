"""릴리스 번들(zip)을 만든다 — 사용자 PC에 필요한 것만, **파이썬까지 담아서** 만든다(사용자 PC에 uv·파이썬이 필요 없다).

    uv run python scripts/build_release.py                  # 화면을 빌드하고 번들을 만든다
    uv run python scripts/build_release.py --skip-ui-build  # apps/ui/dist가 이미 있을 때
    uv run python scripts/build_release.py --expect-tag v1.0.0-beta.1   # 태그가 VERSION과 다르면 실패(CI용)

번들 구조:

    whatever-log-<버전>/
      install.cmd                  설치(더블클릭). 번들 안의 파이썬으로 `whatever-log install`을 실행한다
      whatever-log.cmd             관리 명령 도우미: `whatever-log.cmd status` 등
      release.json  VERSION  LICENSE  README.md
      runtime/                     파이썬 임베더블 배포판 + 의존성(Lib/site-packages) + 이름을 바꾼 실행 파일 두 개
        whatever-log.exe           pythonw.exe의 복사본(콘솔 없음) — 앱 창·기록기·hub가 이 이름으로 뜬다
        whatever-log-cli.exe       python.exe의 복사본(콘솔 있음) — 관리 명령(install 등)용
        python314._pth             앱·패키지 소스 폴더를 모듈 검색 경로에 넣는다(상대 경로)
      apps/<앱>/src  packages/<패키지>/src   파이썬 소스(개발 저장소와 같은 모양 — 경로 규칙이 그대로 맞는다)
      apps/ui/dist                 미리 빌드한 화면

실행 파일 이름을 바꾸는 이유: recorder는 "창을 가진 프로세스의 실행 파일 이름"을 기록한다. 이름이 pythonw.exe면 다른 파이썬 프로그램과 구분되지 않고
작업 관리자에도 Python으로 보인다. 이름만 바꾼 복사본이라 Python 재단의 서명이 그대로 유지된다(내용을 건드리지 않는다).

들어가지 않는 것: 서버(`apps/server`), 화면 소스와 Node 의존성, 테스트, 문서, Docker 파일, 개발 설정, uv.

파이썬 버전은 `.mise.toml`의 `python` 한 곳에서 온다. 그 버전의 임베더블 zip은 python.org에서 받고, **SHA-256을 이 파일에 박아 두고** 확인한다
(버전을 올릴 때는 `EMBEDDED_PYTHON_SHA256`도 같이 바꾼다).

결과는 `release-out/whatever-log-<버전>-win64.zip`이다(저장소의 .gitignore에 들어 있다).

버전은 루트의 `VERSION` 파일 한 곳에서 온다. SemVer 형식이다: `1.0.0`(정식), `1.0.0-beta.1`(베타). 하이픈 뒤에 붙은 것이 있으면 시험 버전이다.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "release-out"
PYTHON_APPS = ("launcher", "desktop", "hub", "recorder", "sync")
ROOT_FILES = ("VERSION", "README.md", "LICENSE")
RELEASE_DIR = ROOT / "scripts" / "release"
SKIP_NAMES = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*))?$")

# 임베더블 파이썬: 버전은 .mise.toml에서, 무결성은 여기 박아 둔 해시로 확인한다. 버전을 바꾸면 해시도 바꿔야 한다(테스트가 둘의 짝을 확인한다).
EMBEDDED_PYTHON_SHA256 = {"3.14.8": "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"}
EMBED_URL = "https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"
RUNTIME_DIR = "runtime"
WINDOWLESS_EXE = "whatever-log.exe"
CONSOLE_EXE = "whatever-log-cli.exe"


def read_version(root: Path = ROOT) -> str:
    """루트의 VERSION 파일을 읽고 SemVer 형식인지 확인한다. 아니면 ValueError."""
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER.match(version):
        raise ValueError(f"VERSION이 SemVer 형식이 아니에요: {version!r} (예: 1.0.0, 1.0.0-beta.1)")
    return version


def channel_of(version: str) -> str:
    """버전의 채널: 정식이면 `stable`, 하이픈 뒤가 있으면 그 첫 부분(`1.0.0-beta.1` → `beta`)."""
    match = SEMVER.match(version)
    if match is None:
        raise ValueError(f"SemVer 형식이 아니에요: {version!r}")
    pre = match.group(4)
    return "stable" if pre is None else pre.split(".")[0]


def python_projects(root: Path = ROOT) -> list[Path]:
    """번들에 넣을 파이썬 프로젝트 폴더들: 사용자 PC에서 도는 앱과 `packages/` 전부(pyproject.toml이 있는 것)."""
    apps = [root / "apps" / name for name in PYTHON_APPS]
    packages = sorted(path for path in (root / "packages").iterdir() if (path / "pyproject.toml").is_file())
    return [*apps, *packages]


def build_ui(root: Path = ROOT) -> None:
    """화면을 빌드한다(화면 쪽 의존성만 설치한다 — 서버용 의존성은 필요 없다). pnpm의 출력은 표준 오류로 보낸다 —
    표준 출력은 마지막의 결과(zip 경로, sha256)만 담아야 워크플로가 그것을 읽을 수 있다."""
    corepack = shutil.which("corepack")
    if corepack is None:
        raise SystemExit("corepack(Node.js)을 찾지 못했어요. Node.js를 설치하거나 --skip-ui-build로 이미 빌드한 화면을 쓰세요.")
    subprocess.run([corepack, "pnpm", "install", "--frozen-lockfile", "--filter", "ui..."], cwd=root, check=True, stdout=sys.stderr)
    subprocess.run([corepack, "pnpm", "build"], cwd=root / "apps" / "ui", check=True, stdout=sys.stderr)


def sha256(path: Path) -> str:
    """파일의 SHA-256(릴리스 설명에 적어 사용자가 받은 파일을 확인할 수 있게 한다)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def python_version(root: Path = ROOT) -> str:
    """번들에 넣을 파이썬 버전(`.mise.toml`의 python). 패치 버전까지 있어야 한다(임베더블 zip이 패치 버전별로 있다)."""
    pinned = tomllib.loads((root / ".mise.toml").read_text(encoding="utf-8"))["tools"]["python"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", pinned):
        raise ValueError(f".mise.toml의 python이 정확한 버전(예: 3.14.8)이 아니에요: {pinned!r}")
    return pinned


def fetch_embedded_python(version: str, cache_dir: Path) -> Path:
    """임베더블 파이썬 zip을 받아(이미 받은 것은 재사용) SHA-256을 확인하고 경로를 돌려준다. 해시가 다르면 SystemExit."""
    expected = EMBEDDED_PYTHON_SHA256.get(version)
    if expected is None:
        raise SystemExit(
            f"파이썬 {version}의 임베더블 배포판 해시가 EMBEDDED_PYTHON_SHA256에 없어요. "
            "python.org에서 받은 zip의 SHA-256을 확인해 scripts/build_release.py에 추가해 주세요."
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / f"python-{version}-embed-amd64.zip"
    if not archive.is_file() or sha256(archive) != expected:
        urllib.request.urlretrieve(EMBED_URL.format(version=version), archive)
    actual = sha256(archive)
    if actual != expected:
        archive.unlink()
        raise SystemExit(f"받은 파이썬 zip의 SHA-256이 달라요(기대 {expected}, 실제 {actual}). 변조되었거나 받다가 깨졌을 수 있어요.")
    return archive


def write_path_file(runtime: Path, source_dirs: list[str]) -> None:
    """`python3NN._pth`를 쓴다: 표준 라이브러리, 의존성 폴더, 앱·패키지 소스 폴더(번들 루트 기준)를 모듈 검색 경로에 넣는다.

    임베더블 파이썬은 이 파일이 있으면 환경변수와 현재 폴더를 무시한다(격리) — 그래서 작업 디렉터리에 놓인 파일이 import되는 일이 없다.
    경로는 이 파일이 있는 폴더(runtime) 기준 상대 경로라서 번들을 어디에 풀어도 맞다.
    """
    # python3.dll(안정 ABI 껍데기)이 아니라 python314.dll처럼 버전이 붙은 것의 이름을 쓴다 — _pth 파일 이름은 이 DLL 이름에서 정해진다
    dll = next(path for path in sorted(runtime.glob("python3*.dll")) if re.fullmatch(r"python3\d+\.dll", path.name))
    name = dll.stem  # python314
    lines = [f"{name}.zip", ".", "Lib\\site-packages", *(f"..\\{folder}" for folder in source_dirs), "import site"]
    (runtime / f"{name}._pth").write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def export_requirements(root: Path, output: Path) -> None:
    """`uv.lock` 그대로의 의존성 목록(워크스페이스 패키지 제외, 개발용 제외)을 파일로 뽑는다."""
    subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--all-packages", "--no-emit-workspace", "-o", str(output)],
        cwd=root,
        check=True,
        stdout=sys.stderr,
    )


def install_dependencies(requirements: Path, target: Path, python: str) -> None:
    """의존성을 target(site-packages)에 설치한다. 이 PC의 파이썬이 아니라 대상(Windows, python 버전)에 맞는 것을 받는다."""
    subprocess.run(
        [
            "uv", "pip", "install", "--target", str(target), "-r", str(requirements), "--require-hashes",
            "--python-platform", "windows", "--python-version", python,
        ],
        check=True,
        stdout=sys.stderr,
    )


def build_runtime(runtime: Path, root: Path = ROOT, cache_dir: Path | None = None) -> None:
    """runtime 폴더를 만든다: 임베더블 파이썬을 풀고, 의존성을 넣고, 실행 파일 이름을 바꾸고, 모듈 검색 경로를 쓴다."""
    version = python_version(root)
    archive = fetch_embedded_python(version, cache_dir or OUT_DIR / "cache")
    with zipfile.ZipFile(archive) as embedded:
        embedded.extractall(runtime)
    # 이름만 바꾼 복사본 — 원래 이름(python.exe·pythonw.exe)은 남기지 않는다. 남기면 어느 쪽으로 실행했는지에 따라 기록되는 이름이 갈린다.
    (runtime / "pythonw.exe").replace(runtime / WINDOWLESS_EXE)
    (runtime / "python.exe").replace(runtime / CONSOLE_EXE)
    site_packages = runtime / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    requirements = runtime.parent / "requirements.txt"
    export_requirements(root, requirements)
    install_dependencies(requirements, site_packages, version)
    requirements.unlink()
    shutil.rmtree(site_packages / "bin", ignore_errors=True)  # 빌드 PC의 경로가 박힌 명령 실행기(keyring.exe 등) — 번들에서는 쓸모없다
    write_path_file(runtime, [(project / "src").relative_to(root).as_posix().replace("/", "\\") for project in python_projects(root)])


def stage(version: str, target: Path, root: Path = ROOT, cache_dir: Path | None = None) -> None:
    """번들에 들어갈 파일들을 target 폴더에 모은다(target은 비어 있거나 없어야 한다)."""
    dist = root / "apps" / "ui" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("apps/ui/dist/index.html이 없어요. --skip-ui-build를 빼고 화면을 먼저 빌드해 주세요.")
    target.mkdir(parents=True)
    for name in ROOT_FILES:
        shutil.copy2(root / name, target / name)
    for project in python_projects(root):
        shutil.copytree(project / "src", target / project.relative_to(root) / "src", ignore=SKIP_NAMES)
    shutil.copytree(dist, target / "apps" / "ui" / "dist")
    build_runtime(target / RUNTIME_DIR, root, cache_dir)
    # cmd는 LF 줄바꿈 배치 파일을 제대로 읽지 못한다(한글 줄과 `if (…)` 블록에서 "명령 구문이 올바르지 않습니다"로 멈춘다 —
    # v1.0.0-beta.1이 이렇게 나갔다). checkout의 줄바꿈 설정과 상관없이 번들에는 항상 CRLF로 넣는다.
    for script_name in ("install.cmd", "whatever-log.cmd"):
        script = (RELEASE_DIR / script_name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        (target / script_name).write_bytes(script)
    # 배포 표시: 이 파일이 있으면 앱은 데이터를 사용자 데이터 폴더에 둔다(common.paths)
    (target / "release.json").write_text(
        json.dumps({"version": version, "channel": channel_of(version)}, indent=2) + "\n", encoding="utf-8"
    )


def make_zip(source: Path, archive: Path) -> None:
    """source 폴더를 `<폴더 이름>/…` 구조의 zip으로 묶는다(항상 같은 순서·시각이라 같은 내용이면 같은 파일이 나온다)."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo.from_file(path, Path(source.name) / path.relative_to(source))
                info.date_time = (2000, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, path.read_bytes())


def main(argv: list[str] | None = None) -> int:
    """번들을 만들고 경로와 해시를 출력한다."""
    parser = argparse.ArgumentParser(description="whatever.log 릴리스 번들을 만든다")
    parser.add_argument("--skip-ui-build", action="store_true", help="화면을 빌드하지 않고 apps/ui/dist를 그대로 쓴다")
    parser.add_argument("--expect-tag", help="이 태그(예: v1.0.0-beta.1)가 VERSION과 다르면 실패한다")
    args = parser.parse_args(argv)

    version = read_version()
    if args.expect_tag is not None and args.expect_tag != f"v{version}":
        print(f"태그({args.expect_tag})와 VERSION(v{version})이 달라요. VERSION을 고치고 다시 태그를 만들어 주세요.", file=sys.stderr)
        return 1
    if not args.skip_ui_build:
        build_ui()

    name = f"whatever-log-{version}"
    folder = OUT_DIR / name
    if folder.exists():
        shutil.rmtree(folder)
    stage(version, folder)
    archive = OUT_DIR / f"{name}-win64.zip"
    make_zip(folder, archive)
    shutil.rmtree(folder)
    print(f"{archive}\nsha256: {sha256(archive)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
