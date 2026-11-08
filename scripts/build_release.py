"""릴리스 번들(zip)을 만든다 — 사용자 PC에 필요한 것만 담는다.

    uv run python scripts/build_release.py                  # 화면을 빌드하고 번들을 만든다
    uv run python scripts/build_release.py --skip-ui-build  # apps/ui/dist가 이미 있을 때
    uv run python scripts/build_release.py --expect-tag v1.0.0-beta.1   # 태그가 VERSION과 다르면 실패(CI용)

번들에 들어가는 것: 파이썬 앱·패키지의 `pyproject.toml`과 `src/`, 미리 빌드한 화면(`apps/ui/dist`), 루트의 `pyproject.toml`·`uv.lock`·
`VERSION`·`README.md`, 설치 스크립트(`install.cmd`), 배포 표시(`release.json`).
들어가지 않는 것: 서버(`apps/server`, Cloudflare는 사용자 PC에서 쓰지 않는다), 화면 소스와 Node 의존성, 테스트, 문서, Docker 파일, 개발 설정.

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
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "release-out"
PYTHON_APPS = ("launcher", "desktop", "hub", "recorder", "sync")
ROOT_FILES = ("pyproject.toml", "uv.lock", "VERSION", "README.md")
INSTALL_SCRIPT = ROOT / "scripts" / "release" / "install.cmd"
SKIP_NAMES = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*))?$")


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


def stage(version: str, target: Path, root: Path = ROOT) -> None:
    """번들에 들어갈 파일들을 target 폴더에 모은다(target은 비어 있거나 없어야 한다)."""
    dist = root / "apps" / "ui" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("apps/ui/dist/index.html이 없어요. --skip-ui-build를 빼고 화면을 먼저 빌드해 주세요.")
    target.mkdir(parents=True)
    for name in ROOT_FILES:
        shutil.copy2(root / name, target / name)
    for project in python_projects(root):
        destination = target / project.relative_to(root)
        destination.mkdir(parents=True)
        shutil.copy2(project / "pyproject.toml", destination / "pyproject.toml")
        shutil.copytree(project / "src", destination / "src", ignore=SKIP_NAMES)
    shutil.copytree(dist, target / "apps" / "ui" / "dist")
    # cmd는 LF 줄바꿈 배치 파일을 제대로 읽지 못한다(한글 줄과 `if (…)` 블록에서 "명령 구문이 올바르지 않습니다"로 멈춘다 —
    # v1.0.0-beta.1이 이렇게 나갔다). checkout의 줄바꿈 설정과 상관없이 번들에는 항상 CRLF로 넣는다.
    script = INSTALL_SCRIPT.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    (target / "install.cmd").write_bytes(script)
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


def sha256(path: Path) -> str:
    """파일의 SHA-256(릴리스 설명에 적어 사용자가 받은 파일을 확인할 수 있게 한다)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
