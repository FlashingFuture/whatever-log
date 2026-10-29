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
띄우고, 떠 있는 동안 계속 감시한다(packages/supervision의 supervise()) —
apps/ui가 "오늘 사용 현황" 등을 그 API로 fetch하기 때문이다. recorder의
수집 루프와는 완전히 분리된 별도 프로세스라, hub가 느려지거나 죽어도
recorder에는 영향이 없다(docs/2026-10-hub-architecture.md 참고). 창이
닫히면 hub 감시도 같이 멈추고 hub를 종료시킨다 — supervise()의
stop_event로 신호를 보낸다.

사용법:
    uv run python -m desktop            # 빌드된 apps/ui/dist 열기
    uv run python -m desktop --dev      # Vite dev server(기본 http://localhost:5173) 열기

`--dev`는 desktop이 Vite dev server를 대신 띄워주는 게 아니라 그 주소를
가리키기만 한다 — apps/ui에서 `pnpm run dev`를 먼저 실행해둬야 한다. 안
그러면 webview가 연결 거부로 빈 화면(또는 알아보기 힘든 오류)만 보여준다.
`--dev`일 때는 webview의 DevTools도 켜진다(`webview.start(debug=True)`) —
이 앱은 pythonw.exe의 콘솔 없는 환경에서 돌아서 평소엔 브라우저 개발자
도구로 디버깅할 방법이 없기 때문이다.
"""

import argparse
import logging
import socket
import sys
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import webview
from hub.__main__ import DEFAULT_PORT as HUB_PORT
from hub.__main__ import EXIT_ALREADY_RUNNING as HUB_EXIT_ALREADY_RUNNING
from hub.__main__ import EXIT_ARGUMENT_ERROR as HUB_EXIT_ARGUMENT_ERROR
from supervision.log_setup import configure_logging
from supervision.supervisor import supervise

DEV_SERVER_URL = "http://localhost:5173"

_APP_DIR = Path(__file__).resolve().parents[2]
_UI_DIST_DIR = _APP_DIR.parent / "ui" / "dist"
_UI_DIST_INDEX = _UI_DIST_DIR / "index.html"

_HUB_READY_TIMEOUT_SECONDS = 5.0
DEFAULT_HUB_SUPERVISOR_LOG_PATH = _APP_DIR / "hub-supervisor.log"

hub_supervisor_logger = logging.getLogger("desktop.hub_supervisor")


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


def _dev_server_is_up(timeout: float) -> bool:
    """Vite dev server(DEV_SERVER_URL)가 떠 있는지 확인한다.

    --dev는 desktop이 그 서버를 대신 띄워주는 게 아니라 가리키기만 하므로,
    apps/ui에서 `pnpm run dev`를 먼저 실행해놓지 않으면 webview가 연결
    거부로 빈 화면만 보여준다 — 그 상태에서는 콘솔도 없어서 원인을 알기
    어렵다. 미리 확인해서 바로 알려준다.
    """
    parsed = urlparse(DEV_SERVER_URL)
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except OSError:
        return False


def _classify_hub_exit(exit_code: int) -> str | None:
    """hub가 재시도해도 안 풀리는 종료 코드로 죽었으면 멈출 사유를, 크래시면
    None을 돌려준다(recorder.supervisor._classify_exit와 같은 패턴)."""
    if exit_code == 0:
        return "hub가 정상 종료했습니다"
    if exit_code == HUB_EXIT_ARGUMENT_ERROR:
        return "hub 인자가 잘못되었습니다"
    if exit_code == HUB_EXIT_ALREADY_RUNNING:
        return "다른 hub가 이미 실행 중입니다"
    return None


def _wait_for_hub_port(port: int, timeout: float) -> None:
    """hub가 포트를 열 때까지 기다린다.

    안 기다리면 창이 뜬 직후 apps/ui의 첫 fetch가 hub가 아직 리스닝하기
    전이라 연결 거부로 실패할 수 있다. hub가 계속 크래시를 반복해도 여기서는
    그냥 타임아웃으로 처리한다 — 왜 못 떴는지는 hub-supervisor.log에 남는다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"hub가 {timeout}초 안에 포트 {port}를 열지 않았습니다.")


def main() -> None:
    """CLI 인자(`--dev`)를 파싱해서 hub를 supervise하며 webview 창을 연다."""
    parser = argparse.ArgumentParser(description="whatever.log 데스크톱 창")
    parser.add_argument(
        "--dev",
        action="store_true",
        help=f"빌드된 파일 대신 Vite dev server({DEV_SERVER_URL})를 연다",
    )
    args = parser.parse_args()

    if args.dev and not _dev_server_is_up(timeout=1.0):
        print(
            f"Vite dev server({DEV_SERVER_URL})가 떠 있지 않습니다.\n"
            "apps/ui에서 `pnpm run dev`를 먼저 실행한 뒤 다시 시도하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    configure_logging(hub_supervisor_logger, DEFAULT_HUB_SUPERVISOR_LOG_PATH)

    stop_event = threading.Event()
    supervisor_thread = threading.Thread(
        target=supervise,
        args=([sys.executable, "-m", "hub"],),
        kwargs={
            "logger": hub_supervisor_logger,
            "classify_exit": _classify_hub_exit,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    supervisor_thread.start()

    try:
        try:
            _wait_for_hub_port(HUB_PORT, _HUB_READY_TIMEOUT_SECONDS)
        except TimeoutError:
            # hub가 콜드 스타트 등으로 늦게 뜰 수 있다. 여기서 예외를 던지면
            # webview.create_window가 전혀 호출되지 않아 창이 아예 안 뜨고,
            # pythonw.exe 환경이라 traceback도 안 보여서 사용자는 아무것도
            # 못 본다. 로그에만 남기고 창은 그대로 연다 — apps/ui가 fetch
            # 실패를 감지해서 화면에 에러로 보여준다.
            hub_supervisor_logger.exception("hub 준비를 기다리지 못했지만 창은 엽니다.")
        webview.create_window("whatever.log", _resolve_url(args.dev))
        # --dev일 때 DevTools를 켠다 — 이 앱은 콘솔 없는 환경(pythonw.exe)에서
        # 돌아서 평소엔 네트워크 탭/콘솔로 디버깅할 방법이 없다.
        webview.start(debug=args.dev)
    finally:
        stop_event.set()
        supervisor_thread.join(timeout=10)


if __name__ == "__main__":
    main()
