"""바뀐 파일에 해당하는 검사만 골라 돌린다 — Biome, 파이썬 테스트(pytest), 화면·서버의 타입 검사와 테스트.

    pnpm check                                    # main에서 갈라진 뒤 바뀐 것(커밋 안 한 것·새 파일 포함)만
    pnpm check:all                                # 전부
    uv run python scripts/check.py --dry-run      # 무엇을 돌릴지 보여 주기만 한다
    uv run python scripts/check.py --only python  # 파이썬 쪽만(CI는 파이썬과 Node를 다른 러너에서 나눠 돌린다)

고르는 규칙:
- 파이썬 앱·패키지의 파일이 바뀌면 그 프로젝트와, 그것에 의존하는 프로젝트(`pyproject.toml`의 dependencies를 거슬러 올라간다)의
  테스트를 돌린다. 예를 들어 `packages/common`이 바뀌면 그것을 쓰는 앱 전부의 테스트가 돈다.
- 파일을 직접 읽어 검사하는 테스트는 따로 이어 둔다(`CROSS_CHECKS`) — 의존 관계로는 찾을 수 없어서다.
- 루트의 파이썬 설정(`pyproject.toml`, `uv.lock`, `.python-version`)이나 CI 워크플로가 바뀌면 파이썬 테스트를 전부,
  루트의 Node 설정이 바뀌면 화면·서버 검사를 전부 돌린다.

파이썬 쪽은 표준 라이브러리만 쓴다 — Node만 돌리는 CI 러너에서는 uv 없이 `python3 scripts/check.py --only node`로 부른다.
"""

import argparse
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "origin/main"

PYTHON_EVERYTHING = ("pyproject.toml", "uv.lock", ".python-version", ".github/workflows/ci.yml")
NODE_EVERYTHING = ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "biome.json", ".github/workflows/ci.yml")

# 로컬 기능이 cloud를 import하지 않는지 모든 앱·패키지의 pyproject.toml과 소스를 읽어 검사한다 — 파이썬 프로젝트가 바뀌면 늘 돌린다
ISOLATION_TEST = "packages/cloud/tests/test_isolation.py"

# 바뀐 경로(앞부분) → 그것을 직접 읽어 검사하는 테스트
CROSS_CHECKS = {
    # 서버의 nameKey를 node로 실행해 goals의 name_key와 비교한다
    "apps/server/src/": ("packages/goals/tests/test_name_key_parity.py",),
    # 번들 만들기·설치 스크립트·릴리스 워크플로·VERSION을 검사한다
    "scripts/": ("scripts/tests",),
    ".github/workflows/release.yml": ("scripts/tests",),
    "VERSION": ("scripts/tests",),
}

# 화면·서버의 검사(pnpm --filter <이름> <스크립트>)
NODE_CHECKS = {
    "ui": ("build", "test"),  # build가 tsc 타입 검사를 포함한다
    "server": ("typecheck", "test"),
}


@dataclass
class Plan:
    """돌릴 검사 목록. 비어 있으면 바뀐 것에 해당하는 검사가 없다는 뜻이다."""

    lint: list[str] | None = None  # None이면 Biome를 돌리지 않고, 빈 목록이면 저장소 전체를 검사한다
    pytest: list[str] = field(default_factory=list)  # 빈 목록이면 돌리지 않는다. ["."]이면 전부
    node: list[str] = field(default_factory=list)  # NODE_CHECKS의 이름

    def is_empty(self) -> bool:
        return self.lint is None and not self.pytest and not self.node


def python_projects(root: Path = ROOT) -> dict[str, tuple[str, set[str]]]:
    """uv 워크스페이스 멤버를 {이름: (폴더, 의존하는 멤버 이름들)}로 읽는다."""
    workspace = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    projects = {}
    for member in workspace["tool"]["uv"]["workspace"]["members"]:
        project = tomllib.loads((root / member / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        names = {_requirement_name(requirement) for requirement in project.get("dependencies", [])}
        projects[project["name"]] = (member, names)
    for name, (member, names) in projects.items():
        projects[name] = (member, names & projects.keys())
    return projects


def _requirement_name(requirement: str) -> str:
    for index, character in enumerate(requirement):
        if not (character.isalnum() or character in "-_."):
            return requirement[:index]
    return requirement


def affected_projects(changed_members: set[str], projects: dict[str, tuple[str, set[str]]]) -> set[str]:
    """바뀐 멤버 폴더들과, 그것을 (직접이든 건너서든) 의존하는 멤버 폴더들."""
    folder_of = {name: member for name, (member, _) in projects.items()}
    affected = {name for name, member in folder_of.items() if member in changed_members}
    while True:
        dependents = {name for name, (_, needs) in projects.items() if needs & affected} - affected
        if not dependents:
            return {folder_of[name] for name in affected}
        affected |= dependents


def plan(changed: list[str], root: Path = ROOT, *, everything: bool = False) -> Plan:
    """바뀐 파일 경로(저장소 기준, `/` 구분)로 돌릴 검사를 정한다. `everything`이면 바뀐 것과 상관없이 전부."""
    if everything:
        return Plan(lint=[], pytest=["."], node=list(NODE_CHECKS))

    result = Plan(lint=[path for path in changed if (root / path).is_file()] or None)

    projects = python_projects(root)
    members = {member for member, _ in projects.values()}
    if any(path in PYTHON_EVERYTHING for path in changed):
        result.pytest = ["."]
    else:
        changed_members = {member for member in members for path in changed if path.startswith(member + "/")}
        tests = {member + "/tests" for member in affected_projects(changed_members, projects)}
        if changed_members:
            tests.add(ISOLATION_TEST)
        for prefix, extra in CROSS_CHECKS.items():
            if any(path == prefix or path.startswith(prefix) for path in changed):
                tests.update(extra)
        result.pytest = sorted(path for path in tests if (root / path).exists())

    if any(path in NODE_EVERYTHING for path in changed):
        result.node = list(NODE_CHECKS)
    else:
        result.node = [name for name in NODE_CHECKS if any(path.startswith(f"apps/{name}/") for path in changed)]
    return result


def changed_files(base: str, root: Path = ROOT) -> list[str]:
    """`base`에서 갈라진 뒤 바뀐 파일 — 커밋한 것, 아직 커밋 안 한 것, git이 모르는 새 파일까지."""

    def git(*args: str) -> list[str]:
        output = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)
        return [line for line in output.stdout.splitlines() if line]

    since_base = git("diff", "--name-only", f"{base}...HEAD")
    uncommitted = git("diff", "--name-only", "HEAD")
    untracked = git("ls-files", "--others", "--exclude-standard")
    return sorted(set(since_base) | set(uncommitted) | set(untracked))


def commands(planned: Plan, *, only: str | None = None) -> list[tuple[str, list[str]]]:
    """계획을 (설명, 명령) 목록으로 바꾼다."""
    corepack = shutil.which("corepack") or "corepack"
    steps = []
    if only != "python" and planned.lint is not None:
        targets = planned.lint or ["."]
        steps.append(
            (
                "Biome",
                [corepack, "pnpm", "exec", "biome", "check", "--no-errors-on-unmatched", "--files-ignore-unknown=true", *targets],
            )
        )
    if only != "node" and planned.pytest:
        targets = [] if planned.pytest == ["."] else planned.pytest
        steps.append(("pytest", [sys.executable, "-m", "pytest", "-q", "-c", str(ROOT / "pyproject.toml"), *targets]))
    if only != "python":
        for name in planned.node:
            for script in NODE_CHECKS[name]:
                steps.append((f"{name} {script}", [corepack, "pnpm", "--filter", name, script]))
    return steps


def main(argv: list[str] | None = None) -> int:
    """바뀐 것에 해당하는 검사를 차례로 돌리고, 하나라도 실패하면 1을 돌려준다(실패해도 나머지는 끝까지 돌린다)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="바뀐 것과 상관없이 전부 검사한다")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"이 커밋에서 갈라진 뒤의 변경을 본다(기본 {DEFAULT_BASE})")
    parser.add_argument("--only", choices=("python", "node"), help="한쪽만 돌린다")
    parser.add_argument("--dry-run", action="store_true", help="돌릴 명령만 보여 준다")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # Python 3.14는 아직 Windows에서 UTF-8이 기본이 아니다

    changed = [] if args.all else changed_files(args.base)
    steps = commands(plan(changed, everything=args.all), only=args.only)
    if not args.all:
        print(f"{args.base} 이후 바뀐 파일 {len(changed)}개")
    if not steps:
        print("바뀐 것에 해당하는 검사가 없어요.")
        return 0

    failed = []
    for label, command in steps:
        program = Path(command[0]).stem
        print(f"\n== {label}: {program} {' '.join(command[1:])}", flush=True)
        if not args.dry_run and subprocess.run(command, cwd=ROOT).returncode != 0:
            failed.append(label)

    if args.dry_run:
        return 0
    print()
    if failed:
        print(f"실패: {', '.join(failed)}")
        return 1
    print(f"통과: {', '.join(label for label, _ in steps)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
