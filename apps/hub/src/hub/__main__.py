"""recorder.db를 읽어 집계 결과를 로컬 HTTP API로 제공하는 중앙 관리소.

apps/desktop(네이티브 창 셸)이 창을 띄울 때 이 프로세스를 자식으로 띄우고,
apps/ui(화면)는 이 서버의 /api/* 엔드포인트를 fetch로 호출한다. recorder의
수집 루프와는 완전히 분리된 별도 프로세스다 — 조회 쿼리가 느려지거나
죽어도 수집에는 영향이 없다(docs/2026-10-hub-architecture.md 참고).

recorder와 같은 방식으로 lock을 쓴다 — apps/desktop이 hub를 재시작하다가
두 인스턴스가 겹치면, 포트 바인딩 실패라는 알기 어려운 에러 대신 "이미
실행 중"을 명확하게 감지해서 바로 멈춘다. 로그도 recorder와 같은 방식(파일
로테이션)으로 남긴다 — 콘솔 없이(apps/desktop의 자식 프로세스로) 뜨므로
print()로는 아무것도 안 남는다.

사용법: python -m hub --port 8787 --db-path path/to/recorder.db
"""

import argparse
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aggregation.today import today_usage
from recorder.__main__ import DEFAULT_DB_PATH
from recorder.storage import open_db
from supervision.lock import AlreadyRunningError, acquire_lock
from supervision.log_setup import configure_logging

DEFAULT_PORT = 8787

_APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOG_PATH = _APP_DIR / "hub.log"

# argparse가 인자 오류에 쓰는 종료 코드와 맞춘다(recorder와 같은 관례) —
# apps/desktop의 supervisor가 이 코드를 받으면 재시작하지 않아야 한다.
EXIT_ARGUMENT_ERROR = 2
# acquire_lock()의 AlreadyRunningError를 구분하기 위한 전용 종료 코드.
# argparse가 이미 2를 쓰므로 겹치지 않게 3을 쓴다(recorder와 동일한 관례).
EXIT_ALREADY_RUNNING = 3

logger = logging.getLogger("hub")

# apps/ui는 apps/desktop이 서빙하는 다른 포트(또는 다른 오리진)에서 뜨기
# 때문에, 이 API를 fetch하는 건 브라우저 기준 cross-origin 요청이다 — 허용
# 헤더가 없으면 CORS로 막힌다. 둘 다 127.0.0.1에서만 뜨는 개인용 로컬 앱이라
# origin을 와일드카드로 허용해도 위험이 없다.
_CORS_HEADERS = {"Access-Control-Allow-Origin": "*"}


def _lock_path_for_port(port: int) -> Path:
    """포트별로 고유한 lock 경로를 쓴다.

    hub 두 인스턴스가 같은 포트를 두고 경쟁하면, 나중 것은 포트 바인딩
    실패(OSError)로 죽는데 그 메시지만 보고는 "이미 떠 있어서"인지 다른
    문제인지 구분하기 어렵다. lock으로 먼저 "이미 실행 중"을 명확하게
    감지한다.
    """
    return _APP_DIR / f"hub-{port}.lock"


class _Handler(BaseHTTPRequestHandler):
    """/api/* 요청을 집계 함수로 넘기고 JSON으로 응답한다."""

    db_path: Path = DEFAULT_DB_PATH

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for key, value in _CORS_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """지금은 /api/today 하나뿐이다 — 늘어나면 라우팅을 분리한다."""
        if self.path == "/api/today":
            conn = open_db(self.db_path)
            try:
                self._send_json(200, today_usage(conn))
            finally:
                conn.close()
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, log_format: str, *args: object) -> None:
        pass  # 기본 동작(stderr에 접근 로그 출력)을 끈다.


def main() -> None:
    """CLI 인자(`--port`, `--db-path`)를 파싱해서 lock을 잡고 API 서버를 띄운다."""
    parser = argparse.ArgumentParser(description="whatever.log 집계 API 서버")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    configure_logging(logger, DEFAULT_LOG_PATH)

    try:
        lock = acquire_lock(_lock_path_for_port(args.port))
    except AlreadyRunningError:
        logger.exception("시작하지 못했습니다.")
        sys.exit(EXIT_ALREADY_RUNNING)

    try:
        _Handler.db_path = args.db_path
        logger.info("포트 %d에서 집계 API를 시작합니다. DB: %s", args.port, args.db_path)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
        server.serve_forever()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
