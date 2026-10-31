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
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from aggregation.range import process_usage_by_bucket, usage_by_range
from common import api_error
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from hub.icons import IconStore
from recorder.__main__ import DEFAULT_DB_PATH
from supervision.lock import AlreadyRunningError, acquire_lock
from supervision.log_setup import configure_logging

DEFAULT_PORT = 8787

_APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOG_PATH = _APP_DIR / "hub.log"
DEFAULT_ICON_CACHE_DIR = _APP_DIR / "icon-cache"

logger = logging.getLogger("hub")

# apps/ui는 apps/desktop이 서빙하는 다른 포트(또는 다른 오리진)에서 뜨기
# 때문에, 이 API를 fetch하는 건 브라우저 기준 cross-origin 요청이다. 응답에는
# 프로세스별 사용 시간(개인 활동 정보)이 들어 있어서, Access-Control-Allow-Origin을
# 와일드카드(*)로 열면 사용자가 띄워둔 아무 웹사이트나 이 API를 fetch해서 읽어갈
# 수 있다 — 127.0.0.1에만 바인딩한 것만으로는 그걸 막지 못한다(브라우저의 로컬
# 네트워크 접근 제한에 기대지 않는다). 요청의 Origin이 127.0.0.1/localhost일
# 때만 그 origin을 그대로 돌려줘서 허용한다 — desktop이 서빙하는 UI(임의
# 포트)와 Vite dev server(5173) 둘 다 이 패턴에 맞는다.
_ALLOWED_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost)(:\d+)?")


def _lock_path_for_port(port: int) -> Path:
    """포트별로 고유한 lock 경로를 쓴다.

    hub 두 인스턴스가 같은 포트를 두고 경쟁하면, 나중 것은 포트 바인딩
    실패(OSError)로 죽는데 그 메시지만 보고는 "이미 떠 있어서"인지 다른
    문제인지 구분하기 어렵다. lock으로 먼저 "이미 실행 중"을 명확하게
    감지한다.
    """
    return _APP_DIR / f"hub-{port}.lock"


# 월 단위(최대 31일) 조회까지 허용한다. 2시간은 전환이 낀 달의 여유분이다 —
# 시계가 1시간 되돌아가는 보통의 일광절약시간뿐 아니라 2시간 되돌아가는 곳
# (예: Antarctica/Troll)의 10월(31일 2시간)도 통과해야 한다. 이보다 긴 구간은
# 틱 수가 많아 쿼리가 무거워지므로 막는다.
_MAX_USAGE_SPAN = timedelta(days=31, hours=2)


def _usage_bounds(query: dict[str, list[str]]) -> tuple[datetime, datetime]:
    """start/end 쿼리 파라미터(타임존이 붙은 ISO 8601)를 검증해 UTC 경계로 돌려준다.

    "오늘/이번 주/이번 달" 경계는 로컬 타임존을 아는 apps/ui가 계산해서 넘긴다
    — hub에서 타임존/일광절약시간을 다시 계산하지 않기 위해서다. 잘못된 값이면
    ValueError를 던지고, 호출부가 그 메시지로 400을 응답한다.

    오프셋의 "+"는 쿼리 문자열에서 공백으로 디코딩되므로, 호출부는 "Z" 표기를
    쓰거나 퍼센트 인코딩해야 한다.
    """
    start_raw = query.get("start", [""])[0]
    end_raw = query.get("end", [""])[0]
    if not start_raw or not end_raw:
        raise ValueError("start와 end가 모두 필요합니다.")

    try:
        start = datetime.fromisoformat(start_raw)
        end = datetime.fromisoformat(end_raw)
    except ValueError as exc:
        raise ValueError("start/end는 ISO 8601 형식이어야 합니다.") from exc

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end에는 타임존(예: Z, +09:00)이 있어야 합니다.")
    if start >= end:
        raise ValueError("start는 end보다 앞이어야 합니다.")
    if end - start > _MAX_USAGE_SPAN:
        raise ValueError("조회 구간은 최대 31일입니다.")

    try:
        return start.astimezone(UTC), end.astimezone(UTC)
    except OverflowError as exc:
        # 0001-01-01T00:00:00+01:00처럼 UTC로 바꾸면 표현 범위를 벗어나는 값.
        raise ValueError("start/end가 표현할 수 있는 날짜 범위를 벗어났습니다.") from exc


# 칸 수 상한. 하루의 시간별(DST 25시간)과 한 달의 날짜별(31일)이 들어가야 한다.
_MAX_BUCKETS = 32


def _usage_edges(query: dict[str, list[str]]) -> list[datetime]:
    """edges 쿼리 파라미터(쉼표로 구분한 ISO 8601 경계 목록)를 검증해 UTC로 돌려준다.

    칸 경계는 start/end와 같은 이유로 apps/ui가 로컬 타임존으로 계산해 넘긴다.
    잘못된 값이면 ValueError를 던진다(호출부가 400으로 응답).
    """
    raw = query.get("edges", [""])[0]
    if not raw:
        raise ValueError("edges가 필요합니다.")
    parts = raw.split(",")
    if len(parts) < 2 or len(parts) > _MAX_BUCKETS + 1:
        raise ValueError(f"edges는 2개 이상 {_MAX_BUCKETS + 1}개 이하여야 합니다.")

    try:
        edges = [datetime.fromisoformat(part) for part in parts]
    except ValueError as exc:
        raise ValueError("edges는 ISO 8601 형식이어야 합니다.") from exc
    if any(edge.tzinfo is None for edge in edges):
        raise ValueError("edges에는 타임존(예: Z, +09:00)이 있어야 합니다.")
    if any(later <= earlier for earlier, later in zip(edges, edges[1:])):
        raise ValueError("edges는 오름차순이어야 합니다.")
    if edges[-1] - edges[0] > _MAX_USAGE_SPAN:
        raise ValueError("조회 구간은 최대 31일입니다.")

    try:
        return [edge.astimezone(UTC) for edge in edges]
    except OverflowError as exc:
        raise ValueError("edges가 표현할 수 있는 날짜 범위를 벗어났습니다.") from exc


_PROCESS_PATH_PREFIX = "/api/processes/"
_PROCESS_USAGE_SUFFIX = "/usage"
_ICON_PATH_PREFIX = "/api/icons/"
# 아이콘은 키(경로+수정시각)가 바뀌어야 내용이 바뀐다 — 캐시 키가 ETag라 오래
# 캐시해도 안전하고, 만료돼도 If-None-Match로 304만 받으면 된다.
_ICON_MAX_AGE_SECONDS = 24 * 60 * 60
# 없음은 recorder가 나중에 경로를 채울 수도 있으니 짧게만 기억한다.
_ICON_MISSING_MAX_AGE_SECONDS = 5 * 60


class _Handler(BaseHTTPRequestHandler):
    """/api/* 요청을 집계 함수로 넘기고 JSON으로 응답한다."""

    db_path: Path = DEFAULT_DB_PATH
    icon_store: IconStore = IconStore(DEFAULT_ICON_CACHE_DIR)

    def _send_json(
        self, status: int, payload: dict, extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        origin = self.headers.get("Origin", "")
        if _ALLOWED_ORIGIN.fullmatch(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """경로별로 처리 함수에 나눠 준다.

        /api/usage는 전체 집계, /api/processes/<이름>/usage는 한 프로세스의 칸별
        집계, /api/icons/<이름>은 아이콘 PNG다.
        """
        parsed = urlparse(self.path)
        if parsed.path == "/api/usage":
            self._get_usage(parsed.query)
        elif parsed.path.startswith(_PROCESS_PATH_PREFIX) and parsed.path.endswith(
            _PROCESS_USAGE_SUFFIX
        ):
            name = parsed.path[len(_PROCESS_PATH_PREFIX) : -len(_PROCESS_USAGE_SUFFIX)]
            self._get_process_usage(unquote(name), parsed.query)
        elif parsed.path.startswith(_ICON_PATH_PREFIX):
            self._get_icon(unquote(parsed.path[len(_ICON_PATH_PREFIX) :]))
        else:
            self._send_json(404, api_error.error_body(api_error.NOT_FOUND, "not found"))

    def _get_usage(self, raw_query: str) -> None:
        """읽기 전용(mode=ro)으로 연다 — hub는 조회만 하는 쪽이라 쓰기 가능한
        연결을 열어둘 이유가 없고, recorder가 쓰는 도중에도 안전하게 읽을 수
        있다(WAL 모드). DB가 아직 없거나(recorder가 한 번도 안 돈 경우) 읽는
        중 문제가 생기면, 응답 없이 연결이 끊기는 대신 503으로 알린다.
        """
        try:
            start, end = _usage_bounds(parse_qs(raw_query))
        except ValueError as exc:
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, str(exc))
            )
            return

        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                payload = usage_by_range(conn, start, end)
            finally:
                conn.close()
        except sqlite3.Error:
            logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
            self._send_json(
                503,
                api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
            )
            return

        self._send_json(200, payload)

    def _get_process_usage(self, process_name: str, raw_query: str) -> None:
        """한 프로세스의 사용 시간을 edges가 나누는 칸별로 돌려준다(상세 화면용)."""
        try:
            edges = _usage_edges(parse_qs(raw_query))
        except ValueError as exc:
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, str(exc))
            )
            return

        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                known = conn.execute(
                    "SELECT 1 FROM processes WHERE name = ?", (process_name,)
                ).fetchone()
                payload = (
                    process_usage_by_bucket(conn, process_name, edges) if known else None
                )
            finally:
                conn.close()
        except sqlite3.Error:
            logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
            self._send_json(
                503,
                api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
            )
            return

        if payload is None:
            self._send_json(
                404, api_error.error_body(api_error.NOT_FOUND, "process not found")
            )
            return
        self._send_json(200, payload)

    def _get_icon(self, process_name: str) -> None:
        """프로세스 이름 → exe 경로(DB) → 아이콘 PNG.

        클라이언트가 경로를 주지 않고 이름만 준다 — 임의 경로의 파일을 열어 보는
        요청이 되지 않도록, 경로는 recorder가 기록해 둔 것만 쓴다. 아이콘이 없는
        경우에도 잠시 캐시하게 해서(브라우저가 같은 404를 계속 다시 묻지 않게)
        차트가 15초마다 다시 그려져도 요청이 늘어나지 않는다.
        """
        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT exe_path FROM processes WHERE name = ?", (process_name,)
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
            self._send_json(
                503,
                api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
            )
            return

        icon = self.icon_store.get(row[0]) if row and row[0] else None
        if icon is None:
            self._send_json(
                404,
                api_error.error_body(api_error.NOT_FOUND, "icon not found"),
                {"Cache-Control": f"private, max-age={_ICON_MISSING_MAX_AGE_SECONDS}"},
            )
            return

        key, png = icon
        etag = f'"{key}"'
        headers = {
            "ETag": etag,
            "Cache-Control": f"private, max-age={_ICON_MAX_AGE_SECONDS}",
        }
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(png)

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
