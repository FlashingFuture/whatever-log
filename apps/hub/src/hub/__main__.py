"""recorder.db를 읽어 집계 결과를 로컬 HTTP API로 제공하는 중앙 관리소.

apps/desktop(네이티브 창 셸)이 창을 띄울 때 이 프로세스를 자식으로 띄우고,
apps/ui(화면)는 이 서버의 /api/* 엔드포인트를 fetch로 호출한다. recorder의
수집 루프와는 완전히 분리된 별도 프로세스다 — 조회 쿼리가 느려지거나
죽어도 수집에는 영향이 없다(docs/2026-10-hub-architecture.md 참고).

사용법: python -m hub --port 8787 --db-path path/to/recorder.db
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aggregation.today import today_usage
from recorder.__main__ import DEFAULT_DB_PATH
from recorder.storage import open_db

DEFAULT_PORT = 8787

# apps/ui는 apps/desktop이 서빙하는 다른 포트(또는 다른 오리진)에서 뜨기
# 때문에, 이 API를 fetch하는 건 브라우저 기준 cross-origin 요청이다 — 허용
# 헤더가 없으면 CORS로 막힌다. 둘 다 127.0.0.1에서만 뜨는 개인용 로컬 앱이라
# origin을 와일드카드로 허용해도 위험이 없다.
_CORS_HEADERS = {"Access-Control-Allow-Origin": "*"}


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
    """CLI 인자(`--port`, `--db-path`)를 파싱해서 API 서버를 띄운다."""
    parser = argparse.ArgumentParser(description="whatever.log 집계 API 서버")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    _Handler.db_path = args.db_path
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
