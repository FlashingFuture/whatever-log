"""사용자 데이터 폴더 안의 프로필 목록(Chromium 계열 공통)."""

import json
from pathlib import Path


def _read_profile_cache(user_data_dir: Path) -> dict[str, str | None]:
    """`Local State`의 {프로필 폴더 이름: 표시 이름 또는 None}. 못 읽거나 모양이 예상과 다르면 {}.

    이름이 없거나 문자열이 아닌 프로필도 폴더 이름은 그대로 남긴다(표시 이름만 None) — 이름이 없다고
    그 프로필의 방문 기록과 아이콘을 못 읽으면 안 된다.
    """
    try:
        state = json.loads((user_data_dir / "Local State").read_text(encoding="utf-8"))
        cache = state["profile"]["info_cache"]
        return {
            folder: info["name"] if isinstance(info.get("name"), str) else None
            for folder, info in cache.items()
            if isinstance(info, dict)
        }
    except (AttributeError, OSError, ValueError, KeyError, TypeError):
        return {}


def read_profile_names(user_data_dir: Path) -> dict[str, str]:
    """{프로필 폴더 이름: 표시 이름}. 표시 이름이 있는 프로필만. `Local State`를 못 읽으면 빈 딕셔너리."""
    return {
        folder: name
        for folder, name in _read_profile_cache(user_data_dir).items()
        if name is not None
    }


def profile_folders(user_data_dir: Path) -> list[str]:
    """프로필 폴더 이름들(표시 이름이 없는 것 포함). `Local State`에 목록이 없으면 폴더 이름으로 찾는다."""
    listed = list(_read_profile_cache(user_data_dir))
    if listed:
        return listed
    try:
        return sorted(
            entry.name
            for entry in user_data_dir.iterdir()
            if entry.is_dir() and (entry.name == "Default" or entry.name.startswith("Profile "))
        )
    except OSError:
        return []
