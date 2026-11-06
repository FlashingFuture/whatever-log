import pytest

from cloud import PROVIDERS, CloudConfig, LoginCancelled, Provider, Session, sign_in

CONFIG = CloudConfig(server_url="https://server.example", google_client_id="client-123")


def test_google_is_the_only_provider_for_now() -> None:
    assert list(PROVIDERS) == ["google"]
    assert PROVIDERS["google"].label == "Google"


def test_sign_in_uses_the_chosen_provider_and_passes_options_through(monkeypatch) -> None:
    seen: dict = {}

    def fake(config, **options):
        seen.update(config=config, **options)
        return Session("tok")

    monkeypatch.setitem(PROVIDERS, "google", Provider("google", "Google", fake))

    def never_cancelled() -> bool:
        return False

    assert sign_in("google", CONFIG, cancelled=never_cancelled) == Session("tok")
    assert seen["config"] is CONFIG and seen["cancelled"] is never_cancelled
    assert "open_browser" not in seen  # 주지 않으면 제공자의 기본값(시스템 브라우저)을 쓴다


def test_a_new_provider_needs_only_an_entry_in_the_list(monkeypatch) -> None:
    monkeypatch.setitem(PROVIDERS, "kakao", Provider("kakao", "Kakao", lambda config, **options: Session("kakao-tok")))

    assert sign_in("kakao", CONFIG) == Session("kakao-tok")


def test_an_unknown_provider_is_rejected() -> None:
    with pytest.raises(KeyError):
        sign_in("kakao", CONFIG)


def test_cancelling_from_the_app_ends_the_wait_without_calling_the_server() -> None:
    calls: list = []

    with pytest.raises(LoginCancelled):
        sign_in(
            "google",
            CONFIG,
            open_browser=lambda url: True,
            cancelled=lambda: True,
            opener=lambda *args, **kwargs: calls.append(args),
        )

    assert calls == []
