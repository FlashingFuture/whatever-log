import urllib.request

import pytest

# desktop이 서빙하는 UI나 Vite dev server가 보내는 Referer. 아이콘 요청은 이 UI에서 온 것만
# 응답하므로(hub.__main__.is_trusted_page) 아이콘 테스트는 이 헤더를 붙여서 요청한다.
UI_REFERER = "http://127.0.0.1:5173/"


@pytest.fixture
def ui_request():
    """UI 페이지가 보낸 것처럼 Referer를 붙인 요청을 만든다(추가 헤더는 덧붙일 수 있다)."""

    def make(url: str, **headers: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"Referer": UI_REFERER, **headers})

    return make
