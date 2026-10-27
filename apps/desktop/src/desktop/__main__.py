"""apps/ui(Vite로 빌드한 조회 화면)를 네이티브 창(webview)으로 띄운다.

개발 중엔 Vite dev server를 가리키고(HMR을 그대로 쓸 수 있음), 빌드 후엔
apps/ui/dist를 로컬 HTTP로 띄워서 연다 — pywebview가 OS의 네이티브
webview(Windows는 WebView2)를 그대로 쓰기 때문에, Electron처럼 Chromium을
따로 묶어 배포하지 않는다 (docs/2026-10-desktop-ui-framework.md 참고).

dist를 file://로 직접 열지 않는 이유: Chromium 계열 엔진은 ES 모듈
스크립트(`<script type="module">`)를 fetch()로 로드하는데, fetch()의
file:// 접근 자체를 막아둬서 코드가 여러 청크로 쪼개지면(동적 import 등)
화면이 안 뜰 수 있다. 지금처럼 번들이 파일 하나뿐이면 당장은 재현 안
되지만, 화면이 복잡해지기 전에 로컬 HTTP 서빙으로 미리 막아둔다.

창을 띄우기 전에 hub(apps/hub, 집계 API 서버)를 자식 프로세스로 함께
띄운다 — apps/ui가 "오늘 사용 현황" 등을 그 API로 fetch하기 때문이다.
recorder의 수집 루프와는 완전히 분리된 별도 프로세스라, hub가 느려지거나
죽어도 recorder에는 영향이 없다(docs/2026-10-hub-architecture.md 참고).

사용법:
    uv run python -m desktop            # 빌드된 apps/ui/dist 열기
    uv run python -m desktop --dev      # Vite dev server(기본 http://localhost:5173) 열기
"""

import argparse
import socket
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import webview
from hub.__main__ import DEFAULT_PORT as HUB_PORT

DEV_SERVER_URL = "http://localhost:5173"

_UI_DIST_DIR = Path(__file__).resolve().parents[3] / "ui" / "dist"
_UI_DIST_INDEX = _UI_DIST_DIR / "index.html"

_HUB_READY_TIMEOUT_SECONDS = 5.0


def _serve_dist(directory: Path) -> str:
    """directory를 로컬 HTTP(127.0.0.1)로 띄우고 base URL을 반환한다.

    포트 0으로 바인딩해서 OS가 비어 있는 포트를 고르게 한다 — 이 창 하나를
    위한 임시 서버라 고정 포트를 쓸 이유가 없다. 창이 떠 있는 동안만
    필요해서 데몬 스레드로 돌리고(메인 프로세스 종료 시 함께 끝남), LAN에
    노출되지 않도록 127.0.0.1에만 바인딩한다.
    """
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}/"


def _resolve_url(use_dev_server: bool) -> str:
    """열 URL을 결정한다 — dev면 Vite dev server, 아니면 로컬 HTTP로 띄운 빌드 결과."""
    if use_dev_server:
        return DEV_SERVER_URL

    if not _UI_DIST_INDEX.exists():
        raise FileNotFoundError(
            f"빌드된 UI를 찾을 수 없습니다: {_UI_DIST_INDEX}\n"
            "apps/ui에서 `pnpm run build`를 먼저 실행하세요."
        )
    return _serve_dist(_UI_DIST_DIR)


def _wait_for_hub(hub_process: subprocess.Popen, port: int, timeout: float) -> None:
    """hub가 포트를 열 때까지 기다린다.

    안 기다리면 창이 뜬 직후 apps/ui의 첫 fetch가 hub가 아직 리스닝하기
    전이라 연결 거부로 실패할 수 있다. hub_process가 이미 죽어버렸으면(예:
    포트 충돌) 타임아웃까지 기다릴 필요 없이 바로 알린다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if hub_process.poll() is not None:
            raise RuntimeError(f"hub가 바로 종료되었습니다 (exit code {hub_process.returncode}).")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"hub가 {timeout}초 안에 포트 {port}를 열지 않았습니다.")


def main() -> None:
    """CLI 인자(`--dev`)를 파싱해서 hub를 띄우고 webview 창을 연다."""
    parser = argparse.ArgumentParser(description="whatever.log 데스크톱 창")
    parser.add_argument(
        "--dev",
        action="store_true",
        help=f"빌드된 파일 대신 Vite dev server({DEV_SERVER_URL})를 연다",
    )
    args = parser.parse_args()

    hub_process = subprocess.Popen([sys.executable, "-m", "hub"])
    try:
        _wait_for_hub(hub_process, HUB_PORT, _HUB_READY_TIMEOUT_SECONDS)
        webview.create_window("whatever.log", _resolve_url(args.dev))
        webview.start()
    finally:
        hub_process.terminate()
        hub_process.wait(timeout=5)


if __name__ == "__main__":
    main()
