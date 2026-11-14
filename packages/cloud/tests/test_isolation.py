"""로그인이 없어도(그리고 `cloud`가 없어도) 기록·집계·목표가 돌아가야 한다는 경계를 지키는 테스트.

서버와 통신하는 코드는 `cloud`에만 둔다. 로컬 기능이 `cloud`를 import하거나 의존성에 넣으면 로그인이
기록의 전제가 되어 버리므로, 소스·의존성·실제 import를 모두 검사한다.

서버를 부르는 쪽은 셋이다: 동기화 로직(`goalsync`), 동기화 에이전트(`apps/sync`), hub(화면의 로그인 버튼과 확인 창이 hub의
API를 거치기 때문이다). 아래 설명은 hub에 대한 것이고, 나머지 둘은 서버 통신이 목적이라 자유롭게 `cloud`를 쓴다.
예외로 보는 이유: 화면의 로그인 버튼이 hub의 계정 API를 거치기 때문이다. 그래도 hub의 기록·집계·목표는 로그인과
무관해야 하므로, hub가 `cloud`를 아는 곳을 어댑터 파일 하나(`hub/cloud_adapter.py`)로 제한하고, 그 import가
함수 안에만 있게 하며(맨 위에서 import하면 `cloud`가 깨졌을 때 hub 전체가 뜨지 않는다), `cloud` 없이도 hub가
뜨고 계정 기능만 "사용할 수 없음"이 되는지 실제로 확인한다.
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
# 서버를 부르는 쪽만 cloud에 의존할 수 있다. 소비자를 더할 때는 위 설명처럼 "어디서, 어떻게" 아는지를 좁히는 테스트도 더한다.
ALLOWED_CONSUMERS: frozenset[str] = frozenset({"hub", "goalsync", "sync"})
# 로컬 기능이 import하거나 의존하면 안 되는 이름들: 서버와 통신하는 코드는 이 둘에만 있다(goalsync는 cloud 위에 있다).
SERVER_FACING = ("cloud", "goalsync")
HUB_CLOUD_ADAPTER = ROOT / "apps" / "hub" / "src" / "hub" / "cloud_adapter.py"
# 로컬 기능의 대표 모듈 — 로그인(cloud) 없이 import되어야 한다.
LOCAL_MODULES = [
    "recorder.__main__",
    "recorder.storage",
    "aggregation.range",
    "goals",
    "chromium.snapshot",
    "hub.__main__",
    "desktop.__main__",
    "notifier.__main__",
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
    names = {folder.name for folder in LOCAL_MEMBERS}
    assert {"recorder", "goals", "aggregation", "desktop"} <= names
    # 서버를 부르는 쪽은 로컬 기능 목록에 없다(hub는 아래 전용 테스트로 더 엄격하게 본다).
    assert not names & {"hub", "goalsync", "sync", "cloud"}


@pytest.mark.parametrize("folder", LOCAL_MEMBERS, ids=lambda folder: folder.name)
def test_local_members_do_not_import_cloud(folder: Path) -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in folder.rglob("*.py")
        if ".venv" not in path.parts
        and set(SERVER_FACING) & _imported_top_level_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize("folder", LOCAL_MEMBERS, ids=lambda folder: folder.name)
def test_local_members_do_not_depend_on_cloud(folder: Path) -> None:
    project = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = [re.split(r"[<>=!~\[; ]", dependency, maxsplit=1)[0].strip() for dependency in project.get("dependencies", [])]
    assert not set(SERVER_FACING) & set(names)


def test_local_modules_import_even_when_cloud_cannot_be_imported() -> None:
    """실제로 `cloud` import를 막은 프로세스에서 로컬 기능의 대표 모듈이 전부 import되는지 확인한다."""
    program = textwrap.dedent(
        f"""
        import importlib, importlib.abc, importlib.util, sys

        class BlockCloud(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in {SERVER_FACING!r}:
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


def _cloud_import_nodes(tree: ast.AST) -> list[ast.stmt]:
    return [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.Import) and any(alias.name.split(".")[0] in SERVER_FACING for alias in node.names))
        or (isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] in SERVER_FACING)
    ]


def test_hub_knows_the_server_side_only_in_the_adapter_file() -> None:
    hub_sources = ROOT / "apps" / "hub" / "src"
    offenders = [
        str(path.relative_to(ROOT))
        for path in hub_sources.rglob("*.py")
        if path != HUB_CLOUD_ADAPTER
        and set(SERVER_FACING) & _imported_top_level_names(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
    assert "cloud" in _imported_top_level_names(HUB_CLOUD_ADAPTER.read_text(encoding="utf-8"))  # 이 테스트가 헛돌지 않게


def test_the_adapters_cloud_import_is_inside_a_function() -> None:
    """맨 위(모듈 수준)에서 import하면 `cloud`가 깨진 환경에서 hub 전체가 뜨지 않는다."""
    tree = ast.parse(HUB_CLOUD_ADAPTER.read_text(encoding="utf-8"))
    module_level = [node for node in tree.body if node in _cloud_import_nodes(tree)]
    in_function = [
        node
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
        if node in _cloud_import_nodes(tree)
    ]

    assert module_level == []
    assert in_function != []


def test_hub_starts_and_only_the_account_feature_is_unavailable_without_cloud() -> None:
    program = textwrap.dedent(
        f"""
        import importlib.abc, sys

        class BlockCloud(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in {SERVER_FACING!r}:
                    raise ImportError("cloud is blocked for this test")

        sys.meta_path.insert(0, BlockCloud())
        import hub.__main__ as hub_main
        import goals  # 목표 기능은 그대로 쓸 수 있다

        snapshot = hub_main._Handler.account.snapshot()
        print(snapshot['available'], snapshot['signed_in'], snapshot['providers'])
        """
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False []"
