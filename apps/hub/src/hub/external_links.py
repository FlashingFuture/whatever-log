"""화면이 시스템 브라우저로 열어 달라고 요청할 수 있는 바깥 주소.

네이티브 창(webview)에서는 `target=_blank` 링크가 기본 브라우저로 열린다고 보장되지 않아서, 화면은 링크 이름만
hub에 알리고 hub가 시스템 브라우저를 연다. 주소는 여기 고정된 목록뿐이다 — 화면(또는 화면 위에서 도는 코드)이
임의의 주소를 열게 하지 않는다.
"""

import webbrowser
from collections.abc import Callable

REPOSITORY_URL = "https://github.com/FlashingFuture/whatever-log"

LINKS: dict[str, str] = {
    # 무엇이 저장되고 무엇이 서버로 나가는지 사용자용으로 설명한 문서
    "privacy": f"{REPOSITORY_URL}/blob/main/docs/data-handling.md",
}


LINK_OPENED = "opened"
LINK_UNKNOWN = "unknown"  # 목록에 없는 이름 — 열지 않았다
LINK_FAILED = "failed"  # 브라우저가 열리지 못했다(기본 브라우저가 없는 환경 등)


def open_link(name: str, opener: Callable[[str], object] = webbrowser.open) -> str:
    """목록에 있는 링크를 시스템 브라우저로 연다. 결과는 LINK_OPENED / LINK_UNKNOWN / LINK_FAILED.

    `webbrowser.open`은 브라우저를 못 열면 예외 없이 False를 돌려주므로 그 값을 실패로 본다. 화면은 실패를 받으면 직접
    열기를 시도한다(`apps/ui`의 자세히 알아보기).
    """
    url = LINKS.get(name)
    if url is None:
        return LINK_UNKNOWN
    try:
        return LINK_OPENED if opener(url) else LINK_FAILED
    except Exception:  # 브라우저 실행기 자체가 실패해도 hub가 오류로 끊기지 않게
        return LINK_FAILED
