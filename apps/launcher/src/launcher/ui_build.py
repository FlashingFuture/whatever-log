"""화면(apps/ui)을 빌드한다. 데스크톱 창은 빌드된 apps/ui/dist를 열기 때문에, 처음 설치할 때 한 번 필요하다."""

import shutil
import subprocess
from pathlib import Path

from launcher.components import REPO_ROOT

UI_DIR = REPO_ROOT / "apps" / "ui"
UI_DIST_INDEX = UI_DIR / "dist" / "index.html"


class UiBuildError(Exception):
    """화면을 빌드하지 못했다(Node/corepack이 없거나 빌드 명령이 실패). 메시지는 사용자에게 그대로 보여 줄 수 있다."""


def is_built(dist_index: Path = UI_DIST_INDEX) -> bool:
    """빌드 결과(dist/index.html)가 있는지."""
    return dist_index.is_file()


def build() -> None:
    """의존성을 설치하고 화면을 빌드한다. 실패하면 UiBuildError."""
    corepack = shutil.which("corepack")
    if corepack is None:
        raise UiBuildError("Node.js(corepack)를 찾지 못했어요. Node.js를 설치한 뒤 다시 실행해 주세요.")
    for command, cwd in (
        ([corepack, "pnpm", "install", "--frozen-lockfile"], REPO_ROOT),
        ([corepack, "pnpm", "build"], UI_DIR),
    ):
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
            raise UiBuildError(f"`{' '.join(command[1:])}`가 실패했어요:\n" + "\n".join(tail))
