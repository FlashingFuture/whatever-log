import socket
import sys
import threading
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from desktop.__main__ import (
    DEV_SERVER_URL,
    HUB_EXIT_ALREADY_RUNNING,
    HUB_EXIT_ARGUMENT_ERROR,
    _classify_hub_exit,
    _dev_server_is_up,
    _resolve_url,
    _wait_for_hub_port,
)


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


def test_wait_for_hub_port_returns_once_port_is_listening() -> None:
    """포트가 열리면(hub가 준비되면) 바로 리턴해야 한다."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    threading.Thread(target=server.accept, daemon=True).start()

    try:
        _wait_for_hub_port(port, timeout=2.0)
    finally:
        server.close()


def test_wait_for_hub_port_times_out_when_port_never_opens() -> None:
    """포트가 안 열리는 상태가 계속되면(hub가 계속 크래시하는 경우 등)
    타임아웃으로 알려야 한다 — 왜 못 떴는지는 supervise()가 로그에 남긴다."""
    # 65535는 실제로 열려 있을 가능성이 거의 없는 포트라 연결이 계속 거부된다.
    with pytest.raises(TimeoutError):
        _wait_for_hub_port(port=65535, timeout=0.3)


@pytest.mark.parametrize(
    ("exit_code", "expected_fragment"),
    [
        (0, "정상 종료"),
        (HUB_EXIT_ARGUMENT_ERROR, "인자가 잘못되었습니다"),
        (HUB_EXIT_ALREADY_RUNNING, "이미 실행 중"),
    ],
)
def test_classify_hub_exit_recognizes_known_codes(exit_code, expected_fragment) -> None:
    """알고 있는 종료 코드는 재시작하지 않을 사유를 돌려줘야 한다."""
    reason = _classify_hub_exit(exit_code)
    assert reason is not None
    assert expected_fragment in reason


def test_classify_hub_exit_treats_unknown_codes_as_crashes() -> None:
    """모르는 종료 코드는 크래시로 보고 None을 돌려줘서 supervise()가
    재시도하게 해야 한다."""
    assert _classify_hub_exit(1) is None


def test_dev_server_is_up_detects_a_listening_port(monkeypatch) -> None:
    """Vite dev server가 떠 있으면(포트가 열려 있으면) True를 돌려줘야 한다."""
    import desktop.__main__ as main_module

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    threading.Thread(target=server.accept, daemon=True).start()

    try:
        monkeypatch.setattr(main_module, "DEV_SERVER_URL", f"http://127.0.0.1:{port}")
        assert _dev_server_is_up(timeout=1.0) is True
    finally:
        server.close()


def test_dev_server_is_up_returns_false_when_nothing_is_listening(monkeypatch) -> None:
    """Vite dev server를 안 띄워놓고 --dev로 실행하면, webview가 연결 거부로
    빈 화면만 보여주기 전에 미리 알아챌 수 있어야 한다."""
    import desktop.__main__ as main_module

    # 65535는 실제로 열려 있을 가능성이 거의 없는 포트라 연결이 계속 거부된다.
    monkeypatch.setattr(main_module, "DEV_SERVER_URL", "http://127.0.0.1:65535")
    assert _dev_server_is_up(timeout=0.3) is False


def test_main_exits_without_launching_hub_when_dev_server_is_down(monkeypatch) -> None:
    """--dev인데 Vite dev server가 안 떠 있으면, hub/webview를 띄우기 전에
    바로 종료해서 안내 메시지가 보이게 해야 한다."""
    import desktop.__main__ as main_module

    monkeypatch.setattr(sys, "argv", ["desktop", "--dev"])
    monkeypatch.setattr(main_module, "DEV_SERVER_URL", "http://127.0.0.1:65535")
    monkeypatch.setattr(main_module, "supervise", MagicMock())

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 1
    main_module.supervise.assert_not_called()


def test_main_enables_devtools_in_dev_mode(tmp_path, monkeypatch) -> None:
    """--dev일 때는 DevTools를 켜야 한다 — pythonw.exe의 콘솔 없는 환경에서
    브라우저 개발자 도구 없이는 디버깅할 방법이 없다."""
    import desktop.__main__ as main_module

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    threading.Thread(target=server.accept, daemon=True).start()

    try:
        monkeypatch.setattr(sys, "argv", ["desktop", "--dev"])
        monkeypatch.setattr(main_module, "DEV_SERVER_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setattr(main_module, "HUB_PORT", 65535)
        monkeypatch.setattr(main_module, "_HUB_READY_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(main_module, "DEFAULT_HUB_SUPERVISOR_LOG_PATH", tmp_path / "hub-supervisor.log")
        monkeypatch.setattr(main_module, "supervise", MagicMock())

        try:
            with patch("desktop.__main__.webview") as mock_webview:
                main_module.main()
        finally:
            main_module.hub_supervisor_logger.handlers.clear()

        mock_webview.start.assert_called_once_with(debug=True)
    finally:
        server.close()


def test_main_opens_window_even_when_hub_is_not_ready_in_time(tmp_path, monkeypatch) -> None:
    """hub가 제때 안 뜨면(콜드 스타트 등) 로그만 남기고도 창은 열어야 한다 —
    안 그러면 webview.create_window가 전혀 호출되지 않아 창이 아예 안 뜨고,
    pythonw.exe 환경이라 traceback도 안 보여서 사용자는 아무것도 못 본다."""
    import desktop.__main__ as main_module

    monkeypatch.setattr(sys, "argv", ["desktop"])
    monkeypatch.setattr(main_module, "_HUB_READY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(main_module, "HUB_PORT", 65535)
    monkeypatch.setattr(main_module, "DEFAULT_HUB_SUPERVISOR_LOG_PATH", tmp_path / "hub-supervisor.log")
    monkeypatch.setattr(main_module, "supervise", MagicMock())
    monkeypatch.setattr(main_module, "_resolve_url", lambda use_dev_server: "http://example.test")

    try:
        with patch("desktop.__main__.webview") as mock_webview:
            main_module.main()
    finally:
        main_module.hub_supervisor_logger.handlers.clear()

    mock_webview.create_window.assert_called_once()
    mock_webview.start.assert_called_once()
