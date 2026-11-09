import threading
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
    yield
    # 이 아래는 monkeypatch가 경로를 되돌리기 **전에** 돈다(monkeypatch를 받은 픽스처라서). 요청을 처리 중인 작업자가 남아 있으면, 경로가
    # 되돌려진 뒤에 그 요청이 진짜 개발용 DB(apps/hub/goals.db 등)를 열 수 있다 — 서버를 닫는 server_close()는 데몬 작업자를 기다리지 않는다.
    _wait_for_request_workers()


@pytest.fixture
def ui_request():
    """UI 페이지가 보낸 것처럼 Referer를 붙인 요청을 만든다(추가 헤더는 덧붙일 수 있다)."""

    def make(url: str, **headers: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"Referer": UI_REFERER, **headers})

    return make


#: ThreadingHTTPServer가 요청마다 띄우는 작업자 스레드의 이름 꼬리(`Thread-7 (process_request_thread)`)
_WORKER_NAME_SUFFIX = "(process_request_thread)"
_WORKER_WAIT_SECONDS = 10.0


def _wait_for_request_workers() -> None:
    """이 테스트가 띄운 hub 요청 작업자가 모두 끝나기를 기다린다. 끝나지 않으면 테스트를 실패시킨다(다음 테스트나 개발용 DB를 건드릴 수 있다)."""
    stuck = []
    for thread in threading.enumerate():
        if thread is threading.current_thread() or not thread.name.endswith(_WORKER_NAME_SUFFIX):
            continue
        thread.join(timeout=_WORKER_WAIT_SECONDS)
        if thread.is_alive():
            stuck.append(thread.name)
    if stuck:
        pytest.fail(f"요청 작업자가 {_WORKER_WAIT_SECONDS:.0f}초 안에 끝나지 않았어요: {stuck}")
