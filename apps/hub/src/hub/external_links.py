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


def open_link(name: str, opener: Callable[[str], object] = webbrowser.open) -> bool:
    """목록에 있는 링크를 시스템 브라우저로 연다. 목록에 없는 이름이면 열지 않고 False."""
    url = LINKS.get(name)
    if url is None:
        return False
    opener(url)
    return True
