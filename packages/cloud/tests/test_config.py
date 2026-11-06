import pytest

from cloud import CloudConfig, load_config
from cloud.config import DEFAULT_SERVER_URL, SERVER_URL_ENV


def test_the_default_points_at_the_deployed_server() -> None:
    assert load_config({}).server_url == DEFAULT_SERVER_URL == "https://whatever-log-server.whateverlog.workers.dev"


def test_the_server_can_be_overridden_for_local_wrangler_dev() -> None:
    assert load_config({SERVER_URL_ENV: "http://127.0.0.1:8790/"}).server_url == "http://127.0.0.1:8790"


@pytest.mark.parametrize(
    "url",
    [
        "http://server.example",  # 평문 http는 로컬만
        "ftp://server.example",
        "https://",
        "server.example",
        "",
        "https://user:pass@server.example",
        "https://server.example?x=1",
        "http://127.0.0.1.evil.example",
    ],
)
def test_insecure_or_malformed_server_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        CloudConfig(server_url=url)


@pytest.mark.parametrize("url", ["https://server.example", "http://localhost:8790", "http://127.0.0.1:8790", "http://[::1]:8790"])
def test_https_and_local_http_are_accepted(url: str) -> None:
    assert CloudConfig(server_url=url).server_url == url


def test_the_google_client_id_can_be_overridden_together_with_the_server() -> None:
    from cloud.config import CLIENT_ID_ENV, GOOGLE_CLIENT_ID

    assert load_config({}).google_client_id == GOOGLE_CLIENT_ID
    assert load_config({CLIENT_ID_ENV: "other-client"}).google_client_id == "other-client"
