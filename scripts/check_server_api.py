"""운영 서버가 이 앱이 요구하는 API 계약 번호를 갖췄는지 확인한다(앱 출시 전에 release 워크플로가 부른다).

서버의 `GET /version`이 돌려준 `api`가 `cloud.compat.REQUIRED_SERVER_API`보다 작으면 실패(종료 코드 1)한다 — 서버를 먼저 배포해야 한다
(docs/deploy.md의 "서버를 먼저, 앱은 그다음"). 서버 주소는 앱의 기본값이고, `WHATEVER_LOG_SERVER_URL`로 바꿀 수 있다(앱과 같은 규칙).

    uv run python scripts/check_server_api.py
"""

import json
import sys
import urllib.request
from collections.abc import Callable
from typing import Any

from cloud.compat import REQUIRED_SERVER_API
from cloud.config import load_config

_USER_AGENT = "whatever-log-release-check"  # 기본 Python-urllib은 Cloudflare가 봇으로 막는다
_TIMEOUT_SECONDS = 15

Fetch = Callable[[str], Any]


def fetch_version(url: str) -> Any:
    """`GET {url}/version`의 JSON."""
    request = urllib.request.Request(f"{url}/version", headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310 — 주소는 앱 설정(https)이다
        return json.loads(response.read(64 * 1024))


def check(server_url: str, required: int = REQUIRED_SERVER_API, fetch: Fetch = fetch_version) -> tuple[bool, str]:
    """(통과 여부, 한 줄 설명)."""
    try:
        payload = fetch(server_url)
    except Exception as error:  # 네트워크·HTTP·JSON 오류 모두 "확인하지 못함"이다 — 확인하지 못했으면 출시하지 않는다
        return False, f"{server_url}/version을 읽지 못했습니다: {type(error).__name__}: {error}"
    api = payload.get("api") if isinstance(payload, dict) else None
    if isinstance(api, bool) or not isinstance(api, int):
        return False, f"{server_url}/version의 응답에 정수 api가 없습니다(아직 /version이 없는 서버일 수 있습니다): {payload!r}"
    commit = payload.get("commit") or "알 수 없음"
    if api < required:
        return False, f"운영 서버의 API 계약 {api} < 이 앱이 요구하는 {required}. 서버를 먼저 배포하세요(커밋 {commit})."
    return True, f"운영 서버 API 계약 {api} ≥ 요구 {required} (커밋 {commit})"


def main() -> int:
    ok, message = check(load_config().server_url)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
