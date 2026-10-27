import socket
import subprocess
import threading
import urllib.request
from unittest.mock import MagicMock

import pytest

from desktop.__main__ import DEV_SERVER_URL, _resolve_url, _wait_for_hub


def test_dev_flag_returns_dev_server_url() -> None:
    """--dev를 주면 빌드 결과 존재 여부와 무관하게 Vite dev server를 가리켜야 한다."""
    assert _resolve_url(use_dev_server=True) == DEV_SERVER_URL


def test_missing_build_raises_a_clear_error(monkeypatch) -> None:
    """빌드를 안 한 채로 띄우면, webview가 빈 화면을 보여주는 대신 바로 에러로
    "pnpm run build를 먼저 하라"고 알려줘야 한다."""
    import desktop.__main__ as main_module

    monkeypatch.setattr(main_module, "_UI_DIST_INDEX", main_module._UI_DIST_INDEX.parent / "missing.html")

    with pytest.raises(FileNotFoundError):
        _resolve_url(use_dev_server=False)


def test_build_is_served_over_http_not_file(tmp_path, monkeypatch) -> None:
    """file://로 직접 열면 Chromium 계열에서 ES 모듈 스크립트가 fetch()의 file://
    차단으로 안 돌 수 있다 — 빌드 결과는 로컬 HTTP로 띄워서 열어야 한다."""
    import desktop.__main__ as main_module

    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")

    monkeypatch.setattr(main_module, "_UI_DIST_DIR", dist_dir)
    monkeypatch.setattr(main_module, "_UI_DIST_INDEX", dist_dir / "index.html")

    url = _resolve_url(use_dev_server=False)

    assert url.startswith("http://127.0.0.1:")
    with urllib.request.urlopen(url, timeout=2) as response:
        assert "ok" in response.read().decode("utf-8")


def test_wait_for_hub_returns_once_port_is_listening() -> None:
    """포트가 열리면(hub가 준비되면) 바로 리턴해야 한다."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    threading.Thread(target=server.accept, daemon=True).start()

    try:
        fake_process = MagicMock(spec=subprocess.Popen)
        fake_process.poll.return_value = None

        _wait_for_hub(fake_process, port, timeout=2.0)
    finally:
        server.close()


def test_wait_for_hub_fails_fast_when_hub_exits_immediately() -> None:
    """hub가 포트 충돌 등으로 바로 죽어버리면, 타임아웃까지 기다리지 않고
    바로 알려야 한다."""
    fake_process = MagicMock(spec=subprocess.Popen)
    fake_process.poll.return_value = 1
    fake_process.returncode = 1

    with pytest.raises(RuntimeError):
        _wait_for_hub(fake_process, port=65535, timeout=2.0)


def test_wait_for_hub_times_out_when_port_never_opens() -> None:
    """hub가 살아있지만 포트를 안 여는 상태가 계속되면 타임아웃으로 알려야 한다."""
    fake_process = MagicMock(spec=subprocess.Popen)
    fake_process.poll.return_value = None

    # 65535는 실제로 열려 있을 가능성이 거의 없는 포트라 연결이 계속 거부된다.
    with pytest.raises(TimeoutError):
        _wait_for_hub(fake_process, port=65535, timeout=0.3)
