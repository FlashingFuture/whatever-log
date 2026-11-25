"""새 버전 확인(docs/updates.md 1단계). GitHub Releases에서 지금보다 높은 가장 새 버전을 찾아 알리기만 한다 — 받기·설치는 사용자가 한다.

- 버전 순서는 SemVer다(`1.0.0-beta.2` < `1.0.0-beta.10` < `1.0.0`). 지금 버전이 시험 버전(`-beta` 등)이면 시험 버전까지, 정식이면 정식만 알린다.
- GitHub에 묻는 것은 마지막 확인이 24시간 지났을 때뿐이다(결과는 데이터 폴더의 `update-check.json`). 화면의 "지금 확인"·CLI는 바로 묻는다.
- 요청에는 고정된 User-Agent만 담는다. GitHub가 이 PC의 IP를 본다는 것은 docs/data-handling.md에 적었고, 사용자가 끌 수 있다.
- 개발 모양(번들이 아님)에서는 확인하지 않는다(`WHATEVER_LOG_UPDATE_CHECK=1`로 켤 수 있다).
"""

import json
import os
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from common import paths

RELEASES_API = "https://api.github.com/repos/FlashingFuture/whatever-log/releases?per_page=30"
RELEASES_PAGE = "https://github.com/FlashingFuture/whatever-log/releases"
CHECK_INTERVAL = timedelta(hours=24)
CACHE_FILE = "update-check.json"
ENABLE_ENV = "WHATEVER_LOG_UPDATE_CHECK"
_USER_AGENT = "whatever-log-update-check"
_TIMEOUT_SECONDS = 5
_MAX_RESPONSE_BYTES = 512 * 1024

_SEMVER = re.compile(
    r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


@dataclass(frozen=True)
class Version:
    """SemVer 버전. 빌드 메타데이터(`+...`)는 순서에 쓰지 않으므로 버린다."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()

    @property
    def is_prerelease(self) -> bool:
        return bool(self.prerelease)

    def _key(self) -> tuple:
        # 정식(시험 식별자 없음)이 같은 숫자의 시험 버전보다 높다. 시험 식별자는 숫자는 숫자로, 글자는 글자로 견주고 숫자가 글자보다 낮다.
        pre = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in self.prerelease)
        return (self.major, self.minor, self.patch, 0 if self.prerelease else 1, pre)

    def __lt__(self, other: "Version") -> bool:
        return self._key() < other._key()

    def __str__(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        return f"{core}-{'.'.join(self.prerelease)}" if self.prerelease else core


def parse_version(text: str) -> Version | None:
    """`1.0.0-beta.2`, `v1.0.0`, `1.0.0-beta.2 (개발)` 같은 글자를 Version으로. 모양이 틀리면 None."""
    match = _SEMVER.fullmatch(text.strip().removesuffix(" (개발)").strip())
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    return Version(int(major), int(minor), int(patch), tuple(pre.split(".")) if pre else ())


def newest_release(releases: Any, current: Version) -> dict[str, str] | None:
    """GitHub Releases 목록에서 지금보다 높은 가장 새 버전(`{"version", "url", "published_at"}`). 없으면 None.

    초안(draft)과 태그 모양이 틀린 것은 건너뛴다. 지금 버전이 정식이면 시험 버전(pre-release 표시 또는 `-` 식별자)은 알리지 않는다.
    주소는 이 저장소의 릴리스 페이지일 때만 쓴다(응답이 다른 주소를 담아도 그대로 열지 않게).
    """
    if not isinstance(releases, list):
        raise ValueError("릴리스 목록이 아닙니다.")
    best: tuple[Version, dict[str, str]] | None = None
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") is True:
            continue
        tag = item.get("tag_name")
        version = parse_version(tag) if isinstance(tag, str) else None
        if version is None:
            continue
        if not current.is_prerelease and (version.is_prerelease or item.get("prerelease") is True):
            continue
        if not current < version:
            continue
        url = item.get("html_url")
        if not isinstance(url, str) or not url.startswith(f"{RELEASES_PAGE}/"):
            url = RELEASES_PAGE
        published = item.get("published_at") if isinstance(item.get("published_at"), str) else ""
        if best is None or best[0] < version:
            best = (version, {"version": str(version), "url": url, "published_at": published})
    return None if best is None else best[1]


class UpdateCheckFailed(Exception):
    """GitHub에 묻지 못했거나 응답을 이해하지 못했다(다음에 다시 묻는다)."""


Fetch = Callable[[], Any]


def fetch_releases() -> Any:
    """GitHub Releases 목록(JSON). 실패하면 UpdateCheckFailed."""
    request = urllib.request.Request(
        RELEASES_API,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310 — 고정된 https 주소
            return json.loads(response.read(_MAX_RESPONSE_BYTES))
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise UpdateCheckFailed(type(error).__name__) from None


def checks_by_default(environ: dict[str, str] | None = None) -> bool:
    """이 설치본에서 확인을 할 수 있는가: 릴리스 번들이거나, 환경 변수로 켰을 때(개발 모양의 시험용)."""
    env = os.environ if environ is None else environ
    return paths.bundle_info() is not None or env.get(ENABLE_ENV) == "1"


class UpdateChecker:
    """새 버전 확인과 그 결과·설정(켜고 끄기)을 데이터 폴더의 작은 JSON에 둔다. 여러 요청이 동시에 와도 GitHub에는 한 번만 묻는다."""

    def __init__(
        self,
        cache_path: Path,
        current: str,
        *,
        supported: bool,
        fetch: Fetch = fetch_releases,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._path = cache_path
        self._current_text = current
        self._current = parse_version(current)
        self._supported = supported and self._current is not None
        self._fetch = fetch
        self._now = now
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._path)
        except OSError:
            pass  # 기억하지 못해도 확인은 된다 — 다음에 다시 묻는다

    def _view(self, data: dict[str, Any]) -> dict[str, Any]:
        latest = data.get("latest") if isinstance(data.get("latest"), dict) else None
        # 기억해 둔 최신 버전이 그사이 설치한 지금 버전 이하면(직접 업데이트했다) 알리지 않는다.
        if latest is not None and self._current is not None:
            seen = parse_version(str(latest.get("version", "")))
            if seen is None or not self._current < seen:
                latest = None
        return {
            "supported": self._supported,
            "enabled": self._supported and data.get("enabled", True) is not False,
            "current": self._current_text,
            "latest": latest,
            "available": latest is not None,
            "checked_at": data.get("checked_at") if isinstance(data.get("checked_at"), str) else None,
            "error": data.get("error") if isinstance(data.get("error"), str) else None,
            "releases_url": RELEASES_PAGE,
        }

    def state(self, *, force: bool = False) -> dict[str, Any]:
        """지금 상태. 확인할 때가 됐으면(24시간, 또는 force) GitHub에 묻는다. 꺼져 있거나 지원하지 않으면 묻지 않는다."""
        with self._lock:
            data = self._load()
            view = self._view(data)
            if not view["enabled"] or self._current is None:
                return view
            checked = view["checked_at"]
            due = force or checked is None
            if not due:
                try:
                    due = self._now() - datetime.fromisoformat(checked) >= CHECK_INTERVAL
                except ValueError:
                    due = True
            if not due:
                return view
            data["checked_at"] = self._now().isoformat()
            try:
                data["latest"] = newest_release(self._fetch(), self._current)
                data.pop("error", None)
            except (UpdateCheckFailed, ValueError) as error:
                # 실패는 기억해 두고(다음 확인 때까지 다시 묻지 않는다) 마지막으로 알던 결과는 그대로 둔다.
                data["error"] = f"새 버전을 확인하지 못했어요({error})."
            self._save(data)
            return self._view(data)

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        """확인을 켜고 끈다. 끄면 GitHub에 묻지 않는다."""
        with self._lock:
            data = self._load()
            data["enabled"] = enabled
            self._save(data)
        return self.state() if enabled else self._view(data)


def default_checker(legacy_dir: Path) -> UpdateChecker:
    """이 설치본의 확인기(데이터 폴더의 `update-check.json`, 지금 버전, 번들일 때만)."""
    return UpdateChecker(
        paths.data_path(legacy_dir, CACHE_FILE),
        paths.version(),
        supported=checks_by_default(),
    )
