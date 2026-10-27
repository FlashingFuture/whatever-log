import pytest

from desktop.__main__ import DEV_SERVER_URL, _resolve_url


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
