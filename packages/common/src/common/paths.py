"""설치 위치와 데이터 위치를 정하는 규칙. 앱들이 DB·로그·lock을 어디에 둘지 같은 기준으로 정하려고 한 곳에 둔다.

두 가지 모양이 있다:

- **개발 모양(저장소를 clone해서 쓸 때)**: 파일이 앱 폴더 안에 생긴다(`apps/recorder/recorder.db` 등). 기존 동작 그대로다.
- **배포 모양(릴리스 번들)**: 번들 루트에 `release.json`이 있다. 이 경우 데이터와 로그는 **사용자 데이터 폴더**
  (`%LOCALAPPDATA%\\whatever.log`)에 둔다 — 새 버전을 새 폴더에 풀어도, 폴더를 지워도 기록과 목표가 남는다.

환경변수 `WHATEVER_LOG_DATA_DIR`이 있으면 두 모양 모두에서 그 폴더를 데이터 폴더로 쓴다(시험·이전 용도).

어느 쪽이든 **같은 이름의 파일은 항상 같은 곳**에 있어야 한다: hub는 recorder.db를 읽고, 동기화 에이전트는 hub의 goals.db를 열기 때문이다.
그래서 경로를 앱마다 따로 정하지 않고 `data_path`로 통일한다.
"""

import json
import os
from pathlib import Path

BUNDLE_MARKER = "release.json"
DATA_DIR_ENV = "WHATEVER_LOG_DATA_DIR"
APP_FOLDER_NAME = "whatever.log"
_VERSION_FILE = "VERSION"


def install_root() -> Path:
    """저장소(또는 릴리스 번들)의 루트 폴더. packages/common/src/common/paths.py 기준."""
    return Path(__file__).resolve().parents[4]


def bundle_info(root: Path | None = None) -> dict | None:
    """릴리스 번들이면 release.json의 내용(버전 등), 개발용 저장소면 None. 깨진 파일은 번들로 보지 않는다."""
    marker = (root or install_root()) / BUNDLE_MARKER
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def version(root: Path | None = None) -> str:
    """지금 설치본의 버전(예: `1.0.0-beta.1`). 개발용 저장소에서는 뒤에 ` (개발)`이 붙는다. 읽지 못하면 `알 수 없음`."""
    base = root or install_root()
    info = bundle_info(base)
    if info and isinstance(info.get("version"), str):
        return info["version"]
    try:
        return (base / _VERSION_FILE).read_text(encoding="utf-8").strip() + " (개발)"
    except OSError:
        return "알 수 없음"


def data_dir(root: Path | None = None, environ: dict[str, str] | None = None) -> Path | None:
    """데이터 폴더(없으면 만든다). 개발 모양이고 환경변수도 없으면 None — 호출부가 앱 폴더를 쓴다."""
    env = os.environ if environ is None else environ
    explicit = env.get(DATA_DIR_ENV)
    if explicit:
        chosen = Path(explicit)
    elif bundle_info(root) is not None:
        base = env.get("LOCALAPPDATA")
        if not base:
            raise RuntimeError("LOCALAPPDATA를 알 수 없어 데이터 폴더를 정하지 못했습니다.")
        chosen = Path(base) / APP_FOLDER_NAME
    else:
        return None
    chosen.mkdir(parents=True, exist_ok=True)
    return chosen


def data_path(legacy_dir: Path, name: str, *, subdir: str | None = None) -> Path:
    """데이터 파일의 경로. 배포 모양이면 `<데이터 폴더>/[subdir/]name`, 개발 모양이면 `legacy_dir/name`(기존 위치).

    subdir은 배포 모양에서만 쓰인다(로그를 `logs/` 아래에 모은다). 개발 모양의 위치는 바꾸지 않는다.
    """
    folder = data_dir()
    if folder is None:
        return legacy_dir / name
    if subdir:
        folder = folder / subdir
        folder.mkdir(parents=True, exist_ok=True)
    return folder / name
