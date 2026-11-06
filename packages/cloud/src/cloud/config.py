"""서버 주소와 Google 클라이언트 ID. 둘 다 공개 값이라 코드에 둔다(클라이언트 비밀은 서버에만 있다)."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_SERVER_URL = "https://whatever-log-server.whateverlog.workers.dev"
GOOGLE_CLIENT_ID = "506740497505-okl0mm0ge5p7kojam78pdur54ej03j3e.apps.googleusercontent.com"
SERVER_URL_ENV = "WHATEVER_LOG_SERVER_URL"
CLIENT_ID_ENV = "WHATEVER_LOG_GOOGLE_CLIENT_ID"
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class CloudConfig:
    """로그인에 필요한 설정."""

    server_url: str
    google_client_id: str = GOOGLE_CLIENT_ID

    def __post_init__(self) -> None:
        """서버 주소가 https이거나 로컬(개발용 `wrangler dev`)인지 확인한다 — 인증 코드가 평문으로 나가지 않게."""
        parts = urlsplit(self.server_url)
        secure = parts.scheme == "https" and bool(parts.hostname)
        local = parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS
        if not (secure or local) or parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError(f"서버 주소는 https(또는 로컬 http)여야 합니다: {self.server_url!r}")


def load_config(environ: dict[str, str] | None = None) -> CloudConfig:
    """기본 설정. 환경 변수 `WHATEVER_LOG_SERVER_URL`로 서버 주소를, `WHATEVER_LOG_GOOGLE_CLIENT_ID`로 Google
    클라이언트 ID를 바꿀 수 있다(로컬 `wrangler dev`나 다른 서버 확인용). 서버가 쓰는 클라이언트 ID와 같아야 로그인된다."""
    env = os.environ if environ is None else environ
    return CloudConfig(
        server_url=env.get(SERVER_URL_ENV, DEFAULT_SERVER_URL).rstrip("/"),
        google_client_id=env.get(CLIENT_ID_ENV, GOOGLE_CLIENT_ID),
    )
