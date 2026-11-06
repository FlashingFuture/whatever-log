"""로그인이 없어도(그리고 `cloud`가 없어도) 기록·집계·목표가 돌아가야 한다는 경계를 지키는 테스트.

서버와 통신하는 코드는 `cloud`에만 둔다. 로컬 기능이 `cloud`를 import하거나 의존성에 넣으면 로그인이
기록의 전제가 되어 버리므로, 소스·의존성·실제 import를 모두 검사한다.
"""

import ast
import re
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
# 서버를 부르는 쪽만 cloud에 의존할 수 있다. 지금은 그런 소비자가 아직 없다 — 생기면 여기에 더한다.
ALLOWED_CONSUMERS: frozenset[str] = frozenset()
# 로컬 기능의 대표 모듈 — 로그인(cloud) 없이 import되어야 한다.
LOCAL_MODULES = [
    "recorder.__main__",
    "recorder.storage",
    "aggregation.range",
    "goals",
    "chromium.snapshot",
    "hub.__main__",
    "desktop.__main__",
]


def _member_folders() -> list[Path]:
    folders = [
        path.parent
        for pattern in ("apps/*/pyproject.toml", "packages/*/pyproject.toml")
        for path in ROOT.glob(pattern)
    ]
    return sorted(
        (folder for folder in folders if folder.name != "cloud" and folder.name not in ALLOWED_CONSUMERS),
        key=lambda folder: folder.name,
    )


LOCAL_MEMBERS = _member_folders()


def _imported_top_level_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_the_member_list_covers_the_local_features() -> None:
    assert {"recorder", "goals", "aggregation", "hub", "desktop"} <= {folder.name for folder in LOCAL_MEMBERS}


@pytest.mark.parametrize("folder", LOCAL_MEMBERS, ids=lambda folder: folder.name)
def test_local_members_do_not_import_cloud(folder: Path) -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in folder.rglob("*.py")
        if ".venv" not in path.parts and "cloud" in _imported_top_level_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize("folder", LOCAL_MEMBERS, ids=lambda folder: folder.name)
def test_local_members_do_not_depend_on_cloud(folder: Path) -> None:
    project = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = [re.split(r"[<>=!~\[; ]", dependency, maxsplit=1)[0].strip() for dependency in project.get("dependencies", [])]
    assert "cloud" not in names


def test_local_modules_import_even_when_cloud_cannot_be_imported() -> None:
    """실제로 `cloud` import를 막은 프로세스에서 로컬 기능의 대표 모듈이 전부 import되는지 확인한다."""
    program = textwrap.dedent(
        f"""
        import importlib, importlib.abc, importlib.util, sys

        class BlockCloud(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name == "cloud" or name.startswith("cloud."):
                    raise ImportError("cloud is blocked for this test")

        sys.meta_path.insert(0, BlockCloud())
        imported = []
        for module in {LOCAL_MODULES!r}:
            if importlib.util.find_spec(module.split(".")[0]) is None:
                continue  # 이 환경에 없는 멤버(그 멤버만 설치한 환경)
            importlib.import_module(module)
            imported.append(module)
        print(",".join(imported))
        """
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stderr
    imported = result.stdout.strip().split(",")
    assert {"recorder.storage", "aggregation.range", "goals"} <= set(imported)
