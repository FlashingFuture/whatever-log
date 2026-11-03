"""Chrome 사용자 데이터 폴더와 프로필 목록."""

import json
import os
from pathlib import Path


def default_user_data_dir() -> Path:
    """Windows에서 Chrome 프로필들이 있는 폴더."""
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"


def read_profile_names(user_data_dir: Path) -> dict[str, str]:
    """{프로필 폴더 이름: 표시 이름}. `Local State`를 못 읽으면 빈 딕셔너리."""
    try:
        state = json.loads((user_data_dir / "Local State").read_text(encoding="utf-8"))
        cache = state["profile"]["info_cache"]
        return {folder: info["name"] for folder, info in cache.items() if "name" in info}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def profile_folders(user_data_dir: Path) -> list[str]:
    """프로필 폴더 이름들. `Local State`에 목록이 있으면 그것을, 없으면 폴더 이름으로 찾는다."""
    names = read_profile_names(user_data_dir)
    if names:
        return list(names)
    try:
        return sorted(
            entry.name
            for entry in user_data_dir.iterdir()
            if entry.is_dir() and (entry.name == "Default" or entry.name.startswith("Profile "))
        )
    except OSError:
        return []
