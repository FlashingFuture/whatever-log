import urllib.request

import pytest

from hub.__main__ import _Handler

# desktop이 서빙하는 UI나 Vite dev server가 보내는 Referer. 아이콘 요청은 이 UI에서 온 것만
# 응답하므로(hub.__main__.is_trusted_page) 아이콘 테스트는 이 헤더를 붙여서 요청한다.
UI_REFERER = "http://127.0.0.1:5173/"


@pytest.fixture(autouse=True)
def _handler_uses_temp_dbs(tmp_path, monkeypatch):
    """hub 서버를 띄우는 테스트가 DB 경로를 따로 정하지 않아도 실제 개발 폴더의 DB(apps/hub/goals.db 등)를 열지 않게 한다.

    경로를 직접 정하는 테스트는 이 값을 덮어쓰면 되고, 끝나면 monkeypatch가 원래 값으로 되돌린다.
    """
    data = tmp_path / "hub-data"
    data.mkdir()
    monkeypatch.setattr(_Handler, "db_path", data / "recorder.db")
    monkeypatch.setattr(_Handler, "goals_db_path", data / "goals.db")
    monkeypatch.setattr(_Handler, "sync_db_path", data / "sync.db")


@pytest.fixture
def ui_request():
    """UI 페이지가 보낸 것처럼 Referer를 붙인 요청을 만든다(추가 헤더는 덧붙일 수 있다)."""

    def make(url: str, **headers: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"Referer": UI_REFERER, **headers})

    return make
