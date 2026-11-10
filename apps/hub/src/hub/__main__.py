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
from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlsplit

from aggregation.range import (
    process_usage_by_bucket,
    site_usage_by_range,
    usage_by_range,
)
from common import api_error
from chromium.browsers import BROWSERS
from chromium.snapshot import remove_stale_work_dirs
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from common.paths import data_path
from goals import sync_status
from goals import (
    META_SYNC_ENABLED,
    GoalNotFoundError,
    GoalStore,
    GoalValidationError,
    SchemaVersionError,
    days_between,
    is_valid_domain,
    is_valid_process_name,
    period_target_minutes,
)
from hub.account_service import (
    AccountService,
    AccountUnavailable,
    LoginInProgress,
    LogoutProblem,
    SyncBusy,
    SyncProblem,
    UnknownProvider,
)
from hub.cloud_adapter import create_cloud_port
from hub.external_links import LINK_FAILED, LINK_OPENED, open_link
from hub.goals_service import (
    BadRequest,
    browsers_with_sites,
    check_write_origin,
    goal_fields,
    goal_json,
    is_local_host,
    progress_payload,
    read_json_object,
    reject_body,
    validation_error_body,
)
from hub.icons import IconStore
from hub.site_icons import SITE_ICON_TTL_SECONDS, WORK_DIR_PREFIX, SiteIconStore
from recorder.__main__ import DEFAULT_DB_PATH
from supervision.lock import AlreadyRunningError, acquire_lock
from supervision.log_setup import configure_logging

DEFAULT_PORT = 8787

_APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOG_PATH = data_path(_APP_DIR, "hub.log", subdir="logs")
DEFAULT_ICON_CACHE_DIR = data_path(_APP_DIR, "icon-cache")
# 사용자의 목표 설정. recorder.db와 파일을 나눈다(쓰기 주체가 섞이지 않게 — docs/goals-design.md).
DEFAULT_GOALS_DB_PATH = data_path(_APP_DIR, "goals.db")
# 동기화 에이전트(apps/sync)의 자기 상태. 이 PC의 기기 ID를 알아보려고 읽기 전용으로만 연다.
DEFAULT_SYNC_DB_PATH = data_path(_APP_DIR.parent / "sync", "sync.db")

logger = logging.getLogger("hub")

# apps/ui는 apps/desktop이 서빙하는 다른 포트(또는 다른 오리진)에서 뜨기
# 때문에, 이 API를 fetch하는 건 브라우저 기준 cross-origin 요청이다. 응답에는
# 프로세스별 사용 시간(개인 활동 정보)이 들어 있어서, Access-Control-Allow-Origin을
# 와일드카드(*)로 열면 사용자가 띄워둔 아무 웹사이트나 이 API를 fetch해서 읽어갈
# 수 있다 — 127.0.0.1에만 바인딩한 것만으로는 그걸 막지 못한다(브라우저의 로컬
# 네트워크 접근 제한에 기대지 않는다). 요청의 Origin이 허용 목록에 **정확히** 있을
# 때만 그 origin을 그대로 돌려줘서 허용한다. 목록은 이 hub를 띄운 쪽이 `--allowed-origin`으로
# 알려 준다: desktop은 자기가 서빙하는 UI의 실제 origin(임의 포트)을, 따로 띄울 때는 기본값인
# Vite dev server(5173)를 쓴다. "아무 localhost 포트"를 허용하지 않으므로, 이 PC에서 도는 다른
# 로컬 웹 서버의 페이지는 읽지도 쓰지도 못한다.
DEFAULT_ALLOWED_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
_ORIGIN_FORMAT = re.compile(r"http://(127\.0\.0\.1|localhost):\d{1,5}")


def parse_origin(text: str) -> str:
    """`--allowed-origin` 값 검사: 로컬 주소의 `http://호스트:포트`(경로 없음)만 받는다. 아니면 argparse 오류."""
    if _ORIGIN_FORMAT.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(
            f"`{text}`는 http://127.0.0.1:<포트> 또는 http://localhost:<포트> 모양이어야 합니다."
        )
    return text


def is_trusted_page(referer: str, allowed_origins: Collection[str] = DEFAULT_ALLOWED_ORIGINS) -> bool:
    """아이콘 요청을 보낸 페이지(Referer)가 우리 UI인지.

    아이콘은 <img>로 불려서 CORS 검사를 받지 않는다. 방문 중인 아무 웹페이지가 이 주소들을
    <img>로 불러 보고 onload/onerror로 "기록된 프로세스·사이트인지"를 알아낼 수 있다. 그래서
    UI(허용된 origin)가 보낸 요청에만 응답하고, 그 밖에는 기록 여부와 무관하게 똑같은 답(404)을
    준다. Referer는 다른 사이트가 꾸며 낼 수 없고, 빼 버리면 거부될 뿐이라 정보가 새지 않는다.
    """
    parts = urlsplit(referer)
    return f"{parts.scheme}://{parts.netloc}" in allowed_origins


def _lock_path_for_port(port: int) -> Path:
    """포트별로 고유한 lock 경로를 쓴다.

    hub 두 인스턴스가 같은 포트를 두고 경쟁하면, 나중 것은 포트 바인딩
    실패(OSError)로 죽는데 그 메시지만 보고는 "이미 떠 있어서"인지 다른
    문제인지 구분하기 어렵다. lock으로 먼저 "이미 실행 중"을 명확하게
    감지한다.
    """
    return data_path(_APP_DIR, f"hub-{port}.lock")


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


# 동기화 확인 창에서 한 번에 보낼 수 있는 선택 개수와 항목 이름의 길이(목표는 최대 20개씩 두 쪽이다).
MAX_SYNC_CHOICES = 100
MAX_SYNC_KEY_LENGTH = 100
MAX_EMAIL_LENGTH = 320
MAX_SESSION_KEY_LENGTH = 64


# 로그에 남길 때 식별자(프로세스 이름·사이트 도메인·기기 ID·목표 번호)를 가리는 경로 모양. 앞쪽부터 맞는 첫 규칙을 쓴다.
_LOG_PATH_RULES = (
    (re.compile(r"^/api/processes/.+/usage$"), "/api/processes/:name/usage"),
    (re.compile(r"^/api/icons/.+$"), "/api/icons/:name"),
    (re.compile(r"^/api/site-icons/.+$"), "/api/site-icons/:domain"),
    (re.compile(r"^/api/devices/.+$"), "/api/devices/:id"),
    (re.compile(r"^/api/goals/\d+$"), "/api/goals/:id"),
)


def loggable_path(path: str) -> str:
    """접근 로그에 남길 경로. 프로세스 이름·사이트 도메인 같은 사용 식별자는 `:name` 같은 자리표시로 바꾼다.

    알 수 없는 경로는 `/api/...`가 아니면 그대로 두지 않고 `/other`로 적는다(모르는 경로에 식별자가 있어도 남기지 않는다).
    """
    for rule, shown in _LOG_PATH_RULES:
        if rule.match(path):
            return shown
    return path if path.startswith("/api/") and path.count("/") <= 3 else "/other"


# 서버 GET /progress가 받는 구간의 최대 일수(apps/server의 parseRange와 같다)
MAX_TOTALS_DAYS = 400
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _day_bounds(query: dict[str, list[str]]) -> tuple[str, str]:
    """`from`·`to`(YYYY-MM-DD, 끝날 포함)를 읽고 검사한다. 틀리면 ValueError(사용자용 문장)."""
    values = {name: query.get(name, []) for name in ("from", "to")}
    if set(query) - {"from", "to"} or any(len(found) != 1 for found in values.values()):
        raise ValueError("from·to(날짜) 하나씩만 보내야 합니다.")
    days = []
    for name, (text,) in values.items():
        if not _DAY.fullmatch(text):
            raise ValueError(f"{name}은 YYYY-MM-DD 형식이어야 합니다.")
        try:
            days.append(date.fromisoformat(text))
        except ValueError:
            raise ValueError(f"{name}이 없는 날짜입니다.") from None
    start, end = days
    if end < start:
        raise ValueError("to는 from보다 앞설 수 없습니다.")
    if (end - start).days + 1 > MAX_TOTALS_DAYS:
        raise ValueError(f"구간은 {MAX_TOTALS_DAYS}일까지입니다.")
    return start.isoformat(), end.isoformat()


def _optional_text(value: object, limit: int) -> bool:
    """None이거나 limit 이하의 문자열인지(확인한 이메일·세션 키 칸 검사)."""
    return value is None or (isinstance(value, str) and len(value) <= limit)
_DEVICE_PATH = re.compile(r"/api/devices/([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})")
# 결과를 알 수 없는 실패(요청을 보냈지만 응답을 받지 못함)에 쓰는 상태 코드. 화면은 이것을 "지워졌는지 확인하라"로 안내한다.
STATUS_OUTCOME_UNKNOWN = 504
_PROCESS_PATH_PREFIX = "/api/processes/"
_GOAL_PATH = re.compile(r"/api/goals/(\d{1,9})")
_PROCESS_USAGE_SUFFIX = "/usage"
_ICON_PATH_PREFIX = "/api/icons/"
_SITE_ICON_PATH_PREFIX = "/api/site-icons/"
# 아이콘은 키(경로+수정시각)가 바뀌어야 내용이 바뀐다 — 캐시 키가 ETag라 오래
# 캐시해도 안전하고, 만료돼도 If-None-Match로 304만 받으면 된다.
_ICON_MAX_AGE_SECONDS = 24 * 60 * 60
# 없음은 recorder가 나중에 경로를 채울 수도 있으니 짧게만 기억한다.
_ICON_MISSING_MAX_AGE_SECONDS = 5 * 60


def _is_missing_site_schema(error: sqlite3.OperationalError) -> bool:
    """사이트 테이블/컬럼이 생기기 전의 옛 DB에서 난 오류인지(다른 DB 오류와 구분)."""
    message = str(error)
    return "no such table: sites" in message or "foreground_site_id" in message


class _Handler(BaseHTTPRequestHandler):
    """/api/* 요청을 집계 함수로 넘기고 JSON으로 응답한다."""

    # 요청을 읽는 소켓의 제한 시간. 본문을 끝까지 보내지 않고 연결만 열어 두는 클라이언트가 처리 스레드를
    # 무기한 붙잡지 못하게 한다(쓰기 응답이나 아이콘 전송에는 영향이 없다).
    timeout = 15

    db_path: Path = DEFAULT_DB_PATH
    goals_db_path: Path = DEFAULT_GOALS_DB_PATH
    sync_db_path: Path = DEFAULT_SYNC_DB_PATH
    # 읽기·쓰기를 허용하는 UI의 origin(정확히 일치). main()이 --allowed-origin으로 바꾼다.
    allowed_origins: frozenset[str] = frozenset(DEFAULT_ALLOWED_ORIGINS)
    icon_store: IconStore = IconStore(DEFAULT_ICON_CACHE_DIR)
    site_icon_store: SiteIconStore = SiteIconStore()
    # 로그인 상태·진행. `cloud`는 처음 계정 API가 불릴 때에야 불러온다(없거나 깨져도 hub의 나머지는 그대로 뜬다).
    account: AccountService = AccountService(create_cloud_port)
    # 화면이 요청한 바깥 링크를 시스템 브라우저로 여는 함수(테스트가 바꾼다).
    link_opener = staticmethod(open_link)

    def _send_json(
        self, status: int, payload: dict, extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        origin = self.headers.get("Origin", "")
        if origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        """본문 없는 응답(삭제 성공 등). CORS 헤더는 _send_json과 같은 규칙이다."""
        self.send_response(status)
        origin = self.headers.get("Origin", "")
        if origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _host_is_local(self) -> bool:
        """Host 헤더가 로컬 주소가 아니면 403으로 거부한다(모든 요청에 적용 — DNS 리바인딩 방어)."""
        if is_local_host(self.headers.get("Host", "")):
            return True
        self._send_json(
            403, api_error.error_body(api_error.FORBIDDEN, "허용되지 않은 호스트입니다.")
        )
        return False

    def _send_bad_request(self, error: BadRequest) -> None:
        """BadRequest를 api_error 응답으로."""
        self._send_json(error.status, api_error.error_body(error.code, error.message))

    def _send_unavailable(self, what: str, error: Exception) -> None:
        """DB를 못 읽거나 쓸 때 503. 원인은 로그에만 남긴다."""
        logger.error("%s를 열지 못했습니다: %s", what, error)
        self._send_json(
            503, api_error.error_body(api_error.UNAVAILABLE, "database unavailable")
        )

    def do_OPTIONS(self) -> None:
        """CORS 사전 요청(preflight). 허용된 UI의 Origin에만 쓰기 메서드를 허용한다고 답한다."""
        if not self._host_is_local():
            return
        origin = self.headers.get("Origin", "")
        if origin not in self.allowed_origins:
            self._send_json(
                403, api_error.error_body(api_error.FORBIDDEN, "허용되지 않은 출처입니다.")
            )
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        """POST: /api/goals(목표 만들기), /api/account/login·logout(계정), /api/links/open(바깥 링크 열기)."""
        if not self._host_is_local():
            return
        path = urlparse(self.path).path
        if path == "/api/goals":
            self._write_goal(None)
        elif path == "/api/account/login":
            self._start_login()
        elif path == "/api/account/logout":
            self._logout()
        elif path == "/api/links/open":
            self._open_link()
        elif path == "/api/sync/apply":
            self._apply_sync()
        elif path == "/api/account/delete":
            self._delete_account()
        else:
            self._send_json(404, api_error.error_body(api_error.NOT_FOUND, "not found"))

    def do_PUT(self) -> None:
        """PUT /api/goals/<id> — 목표를 통째로 바꾼다."""
        if not self._host_is_local():
            return
        match = _GOAL_PATH.fullmatch(urlparse(self.path).path)
        if match:
            self._write_goal(int(match.group(1)))
        else:
            self._send_json(404, api_error.error_body(api_error.NOT_FOUND, "not found"))

    def do_DELETE(self) -> None:
        """DELETE /api/goals/<id>(목표 삭제), /api/account/login(진행 중인 로그인 취소)."""
        if not self._host_is_local():
            return
        path = urlparse(self.path).path
        match = _GOAL_PATH.fullmatch(path)
        if match:
            self._delete_goal(int(match.group(1)))
        elif path == "/api/account/login":
            self._cancel_login()
        elif _DEVICE_PATH.fullmatch(path):
            self._delete_device(_DEVICE_PATH.fullmatch(path).group(1), urlparse(self.path).query)
        else:
            self._send_json(404, api_error.error_body(api_error.NOT_FOUND, "not found"))

    def do_GET(self) -> None:
        """경로별로 처리 함수에 나눠 준다.

        /api/usage는 전체 집계(요약 포함), /api/browsers는 사이트를 기록하는 브라우저 목록, /api/processes/<이름>/usage는 한 프로세스의 칸별
        집계, /api/icons/<이름>은 아이콘 PNG, /api/sites는 사이트(도메인)별 집계,
        /api/site-icons/<도메인>은 사이트 아이콘 PNG다.
        """
        if not self._host_is_local():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/usage":
            self._get_usage(parsed.query)
        elif parsed.path == "/api/goals":
            self._get_goals()
        elif parsed.path == "/api/account":
            self._send_account(200)
        elif parsed.path == "/api/sync/plan":
            self._get_sync_plan()
        elif parsed.path == "/api/sync/status":
            self._get_sync_status()
        elif parsed.path == "/api/devices":
            self._get_devices()
        elif parsed.path == "/api/goals/progress":
            self._get_goal_progress(parsed.query)
        elif parsed.path == "/api/goals/all-devices":
            self._get_goal_totals(parsed.query)
        elif parsed.path == "/api/processes":
            self._get_tracked_processes()
        elif parsed.path == "/api/tracked-sites":
            self._get_tracked_sites()
        elif parsed.path == "/api/browsers":
            self._get_browsers()
        elif parsed.path == "/api/sites":
            self._get_site_usage(parsed.query)
        elif parsed.path.startswith(_SITE_ICON_PATH_PREFIX):
            self._get_site_icon(unquote(parsed.path[len(_SITE_ICON_PATH_PREFIX) :]))
        elif parsed.path.startswith(_PROCESS_PATH_PREFIX) and parsed.path.endswith(
            _PROCESS_USAGE_SUFFIX
        ):
            name = parsed.path[len(_PROCESS_PATH_PREFIX) : -len(_PROCESS_USAGE_SUFFIX)]
            self._get_process_usage(unquote(name), parsed.query)
        elif parsed.path.startswith(_ICON_PATH_PREFIX):
            self._get_icon(unquote(parsed.path[len(_ICON_PATH_PREFIX) :]))
        else:
            self._send_json(404, api_error.error_body(api_error.NOT_FOUND, "not found"))

    def _recorded_process_names(self) -> list[str] | None:
        """recorder가 기록한 프로세스 이름들. DB를 못 읽으면 503을 보내고 None."""
        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                return [row[0] for row in conn.execute("SELECT name FROM processes")]
            finally:
                conn.close()
        except sqlite3.Error as error:
            self._send_unavailable("집계 DB", error)
            return None

    def _get_tracked_processes(self) -> None:
        """추적된(기록된) 프로세스 중 목표에 연결할 수 있는 이름들 — 연결 화면의 선택 목록.

        목표 입력 검증과 같은 규칙(is_valid_process_name)으로 거르므로, 목록에 있는 이름은 연결하면 거부되지
        않는다(설치 도구의 `.tmp` 같은 것은 빠진다).
        """
        names = self._recorded_process_names()
        if names is None:
            return
        linkable = sorted((n for n in names if is_valid_process_name(n)), key=str.casefold)
        self._send_json(200, {"processes": linkable})

    def _recorded_sites(self) -> set[tuple[str, str]] | None:
        """recorder가 기록한 (브라우저 프로세스 이름, 도메인) 쌍들. DB를 못 읽으면 503을 보내고 None.

        사이트 컬럼이 생기기 전의 옛 DB는 hub가 고치지 않고(읽기 전용) 빈 집합으로 본다.
        """
        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                # 먼저 (프로세스 id, 사이트 id) 쌍만 중복 없이 뽑고(recorder가 만든 복합 인덱스로 인덱스만 읽는다),
                # 그 적은 수의 쌍에만 이름을 붙인다. 틱 전체에 조인한 뒤 중복을 제거하지 않는다.
                rows = conn.execute(
                    "SELECT p.name, s.domain FROM ("
                    "  SELECT DISTINCT foreground_process_id, foreground_site_id FROM ticks "
                    "  WHERE foreground_site_id IS NOT NULL AND foreground_process_id IS NOT NULL"
                    ") pairs "
                    "JOIN sites s ON s.id = pairs.foreground_site_id "
                    "JOIN processes p ON p.id = pairs.foreground_process_id"
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.OperationalError as error:
            if _is_missing_site_schema(error):
                return set()
            self._send_unavailable("집계 DB", error)
            return None
        except sqlite3.Error as error:
            self._send_unavailable("집계 DB", error)
            return None
        return {(browser, domain) for browser, domain in rows}

    def _get_tracked_sites(self) -> None:
        """추적된 브라우저 사이트 중 목표에 연결할 수 있는 (브라우저, 도메인)들 — 연결 화면의 선택 목록.

        목표 입력 검증과 같은 규칙으로 거른다(지원하는 브라우저, 올바른 도메인). 브라우저 이름 순, 그 안에서 도메인 순이다.
        """
        recorded = self._recorded_sites()
        if recorded is None:
            return
        browsers = {browser.process_name for browser in BROWSERS}
        linkable = sorted(
            (
                (browser, domain)
                for browser, domain in recorded
                if browser in browsers and is_valid_domain(domain)
            ),
            key=lambda pair: (pair[0].casefold(), pair[1]),
        )
        self._send_json(
            200, {"sites": [{"browser": browser, "domain": domain} for browser, domain in linkable]}
        )

    def _check_account_write(self, *, json_body: bool) -> dict | None:
        """계정 쓰기 요청의 출처·본문 형식을 검사한다. 통과하면 본문(없는 요청이면 빈 dict), 아니면 응답을 보내고 None."""
        try:
            check_write_origin(self.headers.get("Origin"), self.allowed_origins)
            if not json_body:
                reject_body(self.headers)
                return {}
            return read_json_object(self.headers, self.rfile)
        except BadRequest as error:
            self._send_bad_request(error)
            return None

    def _send_account(self, status: int, extra: dict | None = None) -> None:
        """현재 계정 상태를 응답한다(토큰은 어디에도 없다). 계정 기능을 못 읽으면 503."""
        try:
            payload = self.account.snapshot()
        except Exception as error:  # 자격 증명 관리자 등 환경 문제 — 다른 API에 영향 없이 이 응답만 실패한다
            logger.error("계정 상태를 읽지 못했습니다: %s", type(error).__name__)
            self._send_json(
                503, api_error.error_body(api_error.UNAVAILABLE, "계정 상태를 읽지 못했습니다.")
            )
            return
        self._send_json(
            status,
            {
                **payload,
                "sync_enabled": self._sync_enabled(),
                "deletion_uncertain": self._deletion_uncertain(payload.get("session")),
                **(extra or {}),
            },
        )

    def _sync_enabled(self) -> bool:
        """사용자가 확인 창에서 동기화를 켰는지(이 PC의 goals.db 값 — 서버와 통신하지 않는다). 읽지 못하면 꺼진 것으로 본다."""
        try:
            with GoalStore(self.goals_db_path) as store:
                return store.get_meta(META_SYNC_ENABLED) == "1"
        except (sqlite3.Error, SchemaVersionError):
            return False

    def _deletion_uncertain(self, session: object) -> bool:
        """이 로그인에서 보낸 계정 삭제의 결과를 알 수 없는 채로 남아 있는가(goals.db의 표시가 지금 세션과 같을 때만).

        이전 세션의 표시는 지금 로그인과 무관하므로 세지 않는다. 읽지 못하면 아니라고 본다(화면에 근거 없는 경고를 띄우지 않는다).
        """
        if not isinstance(session, str):
            return False
        try:
            with GoalStore(self.goals_db_path) as store:
                return store.get_meta("deletion_uncertain") == session
        except (sqlite3.Error, SchemaVersionError):
            return False

    def _start_login(self) -> None:
        """POST /api/account/login {"provider"} — 로그인을 시작한다(브라우저가 열린다). 진행은 GET /api/account로 본다."""
        body = self._check_account_write(json_body=True)
        if body is None:
            return
        provider = body.get("provider")
        if set(body) != {"provider"} or not isinstance(provider, str):
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, "provider 칸 하나만 보내야 합니다.")
            )
            return
        try:
            self.account.start_login(provider)
        except UnknownProvider:
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, "지원하지 않는 로그인 방식입니다.")
            )
            return
        except LoginInProgress:
            self._send_json(
                409, api_error.error_body(api_error.INVALID_REQUEST, "이미 로그인이 진행 중입니다.")
            )
            return
        except SyncBusy:
            self._send_json(
                409, api_error.error_body(api_error.INVALID_REQUEST, "계정을 지우는 중이라 지금은 로그인할 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
            )
            return
        except AccountUnavailable:
            self._send_account_unavailable()
            return
        self._send_account(202)

    def _cancel_login(self) -> None:
        """DELETE /api/account/login — 진행 중인 로그인을 취소한다(진행 중이 아니어도 같다)."""
        if self._check_account_write(json_body=False) is None:
            return
        self.account.cancel_login()
        self._send_account(200)

    def _logout(self) -> None:
        """POST /api/account/logout — 이 PC의 로그인 정보를 지운다(서버 토큰 폐기는 가능하면)."""
        if self._check_account_write(json_body=False) is None:
            return
        try:
            revoked = self.account.sign_out()
        except AccountUnavailable:
            self._send_account_unavailable()
            return
        except LogoutProblem as error:
            self._send_json(500, api_error.error_body(api_error.INTERNAL, error.message))
            return
        self._send_account(200, {"revoked_on_server": revoked})

    def _send_sync_problem(self, problem: SyncProblem) -> None:
        """동기화 요청의 실패: 로그인이 필요하면 409, 결과를 알 수 없으면 504, 서버 문제면 503(사유는 사용자용 문장)."""
        if problem.signed_out:
            self._send_json(409, api_error.error_body(api_error.INVALID_REQUEST, problem.message))
        elif problem.uncertain:
            self._send_json(STATUS_OUTCOME_UNKNOWN, api_error.error_body(api_error.UNAVAILABLE, problem.message))
        else:
            self._send_json(503, api_error.error_body(api_error.UNAVAILABLE, problem.message))

    def _get_sync_plan(self) -> None:
        """GET /api/sync/plan — 로그인 직후 "무엇을 서버에 올릴까요?" 확인 창의 내용(서버 목록과 이 PC 목록을 견준 것)."""
        try:
            plan = self.account.sync_plan(self.goals_db_path)
        except AccountUnavailable:
            self._send_account_unavailable()
            return
        except SyncProblem as problem:
            self._send_sync_problem(problem)
            return
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        self._send_json(200, plan)

    def _apply_sync(self) -> None:
        """POST /api/sync/apply {"accepted": [key…], "email", "session"} — 체크한 항목만 서버에 올리고·합치고·가져온다. 체크하지 않은 이 PC 목표는 올리지 않는다."""
        body = self._check_account_write(json_body=True)
        if body is None:
            return
        accepted = body.get("accepted")
        email = body.get("email")
        session = body.get("session")
        if set(body) != {"accepted", "email", "session"}:
            # 어느 칸이 어긋났는지 로그에 남긴다(값은 남기지 않는다). 화면이 낡은 빌드일 때 원인을 바로 알 수 있다.
            logger.warning("sync apply 본문 칸이 맞지 않음: 받은 칸=%s", sorted(str(key) for key in body))
        if (
            set(body) != {"accepted", "email", "session"}
            or not _optional_text(email, MAX_EMAIL_LENGTH)
            or not _optional_text(session, MAX_SESSION_KEY_LENGTH)
            or not isinstance(accepted, list)
            or len(accepted) > MAX_SYNC_CHOICES
            or not all(isinstance(key, str) and 0 < len(key) <= MAX_SYNC_KEY_LENGTH for key in accepted)
        ):
            self._send_json(
                400,
                api_error.error_body(
                    api_error.INVALID_REQUEST,
                    "accepted(항목 이름 목록), email·session(확인한 로그인) 칸만 보내야 합니다.",
                ),
            )
            return
        try:
            result = self.account.sync_apply(self.goals_db_path, accepted, email, session)
        except AccountUnavailable:
            self._send_account_unavailable()
            return
        except SyncBusy:
            self._send_json(409, api_error.error_body(api_error.INVALID_REQUEST, "이미 동기화를 처리하는 중입니다."))
            return
        except SyncProblem as problem:
            self._send_sync_problem(problem)
            return
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        self._send_json(200, result)

    def _get_sync_status(self) -> None:
        """GET /api/sync/status — 동기화가 잘 되고 있는지(꺼짐/기다리는 중/곧 동기화/정상/오류/에이전트 멈춤). 이 PC의 goals.db만 읽고
        서버를 부르지 않는다."""
        try:
            with GoalStore(self.goals_db_path) as store:
                enabled = store.get_meta(META_SYNC_ENABLED) == "1"
                record = sync_status.read_record(store)
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        described = sync_status.describe(
            record, enabled=enabled, now=datetime.now(UTC), signed_in_since=self.account.signed_in_since()
        )
        self._send_json(200, described)

    def _get_devices(self) -> None:
        """GET /api/devices — 달성도를 보낸 기기들(서버에서 받는다). 이 PC의 기기에는 `is_this_device`가 켜진다."""
        try:
            result = self.account.list_devices(self.goals_db_path, self.sync_db_path)
        except AccountUnavailable:
            self._send_account_unavailable()
            return
        except SyncProblem as problem:
            self._send_sync_problem(problem)
            return
        self._send_json(200, result)

    def _delete_device(self, device_id: str, query: str) -> None:
        """DELETE /api/devices/<id>?email=…&session=… — 그 기기가 보낸 달성 기록을 서버에서 지운다.

        email·session은 기기 목록을 받았을 때의 로그인이다. 지금 로그인과 다르면 거절한다(계정 A의 목록에서 누른 삭제가 B의 기록을 지우지 않게).
        이 PC의 기기는 거절하고, 이 PC의 기기를 확인할 수 없을 때(동기화를 켰는데 에이전트가 기기 ID를 아직 알리지 않음)도 거절한다.
        """
        if self._check_account_write(json_body=False) is None:
            return
        values = parse_qs(query, keep_blank_values=True)
        emails = values.get("email", [])
        sessions = values.get("session", [])
        if (
            set(values) - {"email", "session"}
            or len(emails) != 1
            or len(sessions) != 1
            or len(emails[0]) > MAX_EMAIL_LENGTH
            or not 0 < len(sessions[0]) <= MAX_SESSION_KEY_LENGTH
        ):
            self._send_json(
                400,
                api_error.error_body(api_error.INVALID_REQUEST, "email과 session을 하나씩만 쿼리로 보내야 합니다."),
            )
            return
        confirmed = emails[0] or None  # 빈 값은 "이메일을 알 수 없는 로그인"이다
        try:
            self.account.delete_device(self.goals_db_path, self.sync_db_path, device_id, confirmed, sessions[0])
        except AccountUnavailable:
            self._send_account_unavailable()
            return
        except SyncProblem as problem:
            self._send_sync_problem(problem)
            return
        self._send_empty(204)

    def _delete_account(self) -> None:
        """POST /api/account/delete {"email", "session"} — 서버의 계정과 모든 데이터를 지운다(되돌릴 수 없다). email·session은 사용자가
        확인한 로그인이고, 지금 로그인과 다르면 거절한다. 서버 삭제에 성공한 뒤에만 이 PC의 로그인·동기화 연결을 정리한다."""
        body = self._check_account_write(json_body=True)
        if body is None:
            return
        email = body.get("email")
        session = body.get("session")
        if (
            set(body) != {"email", "session"}
            or not _optional_text(email, MAX_EMAIL_LENGTH)
            or not (isinstance(session, str) and 0 < len(session) <= MAX_SESSION_KEY_LENGTH)
        ):
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, "email과 session 칸만 보내야 합니다.")
            )
            return
        try:
            result = self.account.delete_account(self.goals_db_path, email, session)
        except AccountUnavailable:
            self._send_account_unavailable()
            return
        except SyncBusy:
            self._send_json(409, api_error.error_body(api_error.INVALID_REQUEST, "다른 동기화 작업을 처리하는 중입니다."))
            return
        except SyncProblem as problem:
            self._send_sync_problem(problem)
            return
        self._send_account_after_delete(result)

    def _send_account_after_delete(self, result: dict) -> None:
        """계정 삭제 뒤의 응답. 서버에서 이미 지워졌으므로, 상태를 읽지 못해도 503을 보내지 않고 삭제 결과를 200으로 알린다.

        (503을 보내면 화면은 "지우지 못했다"로 안내한다 — 이미 지워진 계정에 대해 틀린 말이다.) 다만 **읽지 못한 것은 단정하지 않는다**:
        계정 상태를 읽지 못했으면 로그인 여부를 응답에 넣지 않고(화면이 다시 읽는다), 동기화 설정은 실제로 읽은 값을 준다 — 이 PC의 정리
        (`connections_cleared`)가 실패해 설정이 켜진 채 남았다면 켜져 있다고 그대로 알린다.
        """
        payload: dict = {}
        try:
            payload = self.account.snapshot()
        except Exception as error:
            logger.error("계정 삭제 뒤 상태를 읽지 못했습니다: %s", type(error).__name__)
        self._send_json(
            200,
            {**payload, "sync_enabled": self._sync_enabled(), "deletion_uncertain": False, "state_known": bool(payload), **result},
        )

    def _send_account_unavailable(self) -> None:
        """계정 기능을 쓸 수 없는 환경(cloud 없음)의 요청에 503."""
        self._send_json(
            503, api_error.error_body(api_error.UNAVAILABLE, "이 설치에서는 로그인 기능을 쓸 수 없습니다.")
        )

    def _open_link(self) -> None:
        """POST /api/links/open {"link"} — 고정된 목록의 바깥 링크를 시스템 브라우저로 연다."""
        body = self._check_account_write(json_body=True)
        if body is None:
            return
        link = body.get("link")
        if set(body) != {"link"} or not isinstance(link, str):
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, "link 칸 하나만 보내야 합니다.")
            )
            return
        outcome = self.link_opener(link)
        if outcome == LINK_OPENED:
            self._send_empty(204)
        elif outcome == LINK_FAILED:
            # 화면이 직접 열기를 시도할 수 있게 실패를 알린다(204로 답하면 열린 줄 안다).
            self._send_json(
                503, api_error.error_body(api_error.UNAVAILABLE, "브라우저를 열지 못했습니다.")
            )
        else:
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, "열 수 없는 링크입니다.")
            )

    def _get_goals(self) -> None:
        """저장된 목표 목록."""
        try:
            with GoalStore(self.goals_db_path) as store:
                goals = store.list_goals()
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        self._send_json(200, {"goals": [goal_json(goal) for goal in goals]})

    def _get_goal_progress(self, raw_query: str) -> None:
        """구간의 목표별 수행 시간과 요약(홈 왼쪽 요약용). 수행 시간 = 연결 프로세스의 활성 시간 합."""
        try:
            start, end = _usage_bounds(parse_qs(raw_query))
        except ValueError as exc:
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, str(exc))
            )
            return
        try:
            with GoalStore(self.goals_db_path) as store:
                goals = store.list_goals()
                # 달성률의 분모: 구간의 각 날짜(이 PC의 시간대)에 그날 적용된 목표의 하루 목표 분을 더한 것(정의는 goals.targets)
                targets = period_target_minutes(store, days_between(start, end))
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                usage = usage_by_range(conn, start, end)
                site_usage: dict[str, list] = {}
                for browser in browsers_with_sites(goals):
                    try:
                        site_usage[browser] = site_usage_by_range(conn, browser, start, end)["by_site"]
                    except sqlite3.OperationalError as error:
                        if not _is_missing_site_schema(error):
                            raise
                        site_usage[browser] = []  # 사이트 컬럼이 없는 옛 DB — 사이트 시간은 0이다
            finally:
                conn.close()
        except sqlite3.Error as error:
            self._send_unavailable("집계 DB", error)
            return
        self._send_json(200, progress_payload(goals, usage, site_usage, targets))

    def _get_goal_totals(self, raw_query: str) -> None:
        """GET /api/goals/all-devices?from=YYYY-MM-DD&to=YYYY-MM-DD — 목표별 모든 기기의 수행 시간 합계(분, 끝날 포함).

        홈 요약의 "전체 xx분 | 현 기기 xx분"에서 **전체**를 채운다(현 기기는 `/api/goals/progress`). 이 요청은 **항상 200**이다 —
        다른 기기의 기록을 받을 수 없어도(로그인 전, 동기화 꺼짐, 서버에 닿지 못함) 화면은 이 PC의 값을 그대로 보여 주고, 합계 칸만 달라지면 된다.
        `state`: `local`(받을 수 없는 상태 — 이 PC의 값이 전체다) / `synced`(서버 합계) / `unavailable`(받으려 했지만 실패 — 합계 칸을 "-"로 둔다).
        입력(날짜 형식, 끝날이 시작일보다 앞, 400일 초과)이 틀린 경우만 400이다.
        """
        try:
            start_day, end_day = _day_bounds(parse_qs(raw_query))
        except ValueError as exc:
            self._send_json(400, api_error.error_body(api_error.INVALID_REQUEST, str(exc)))
            return
        try:
            result = self.account.goal_totals(self.goals_db_path, start_day, end_day)
        except AccountUnavailable:
            result = {"state": "local", "goals": []}
        except SyncProblem as problem:
            logger.info("모든 기기 합계를 받지 못했습니다: %s", "로그인 필요" if problem.signed_out else "서버 문제")
            result = {"state": "unavailable", "goals": []}
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        self._send_json(200, result)

    def _write_goal(self, goal_id: int | None) -> None:
        """목표 생성(goal_id가 None)·교체. 출처·본문 형식을 먼저 검사하고, 입력은 goals가 엄격하게 검증한다.

        연결할 프로세스는 recorder가 기록한 이름이어야 한다(기록된 적 없는 이름을 연결해 수행 시간이
        영원히 0이 되는 일을 막는다).
        """
        try:
            check_write_origin(self.headers.get("Origin"), self.allowed_origins)
            fields = goal_fields(read_json_object(self.headers, self.rfile))
        except BadRequest as error:
            self._send_bad_request(error)
            return
        # 연결할 것이 없으면 기록 DB를 읽을 이유가 없다 — DB를 못 읽는 중에도 연결 없는 목표는 저장된다.
        recorded: list[str] | None = None
        if fields["processes"]:
            recorded = self._recorded_process_names()
            if recorded is None:
                return
        recorded_sites: set[tuple[str, str]] | None = None
        if fields["sites"]:
            recorded_sites = self._recorded_sites()
            if recorded_sites is None:
                return
        known = {
            "known_processes": recorded,
            "known_sites": recorded_sites,
            "known_browsers": {browser.process_name for browser in BROWSERS},
        }
        try:
            with GoalStore(self.goals_db_path) as store:
                if goal_id is None:
                    goal = store.create(**fields, **known)
                else:
                    goal = store.update(goal_id, **fields, **known)
        except GoalValidationError as error:
            self._send_json(400, validation_error_body(error))
            return
        except GoalNotFoundError:
            self._send_json(404, api_error.error_body(api_error.NOT_FOUND, "goal not found"))
            return
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        self._send_json(201 if goal_id is None else 200, goal_json(goal))

    def _delete_goal(self, goal_id: int) -> None:
        """목표를 지운다(연결 정보도 같이). 출처를 검사하고, 지난 날의 스냅샷은 남는다."""
        try:
            check_write_origin(self.headers.get("Origin"), self.allowed_origins)
            reject_body(self.headers)
        except BadRequest as error:
            self._send_bad_request(error)
            return
        try:
            with GoalStore(self.goals_db_path) as store:
                store.delete(goal_id)
        except GoalNotFoundError:
            self._send_json(404, api_error.error_body(api_error.NOT_FOUND, "goal not found"))
            return
        except (sqlite3.Error, SchemaVersionError) as error:
            self._send_unavailable("목표 DB", error)
            return
        self._send_empty(204)

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

    def _get_browsers(self) -> None:
        """사이트(도메인)를 기록하는 브라우저 프로세스 이름 목록.

        화면이 어느 프로세스의 상세에 사이트 목록을 붙일지 알려고 쓴다. 목록의 원본은
        chromium.browsers(recorder가 쓰는 것과 같은 표)라서, 화면이 자기 목록을 따로 들고 있다가
        서로 어긋나는 일이 없다. 기록된 데이터가 아니라 지원 범위라 DB를 읽지 않고, 민감하지 않아
        아이콘처럼 요청한 페이지를 따지지 않는다.
        """
        self._send_json(200, {"browsers": [browser.process_name for browser in BROWSERS]})

    def _get_site_usage(self, raw_query: str) -> None:
        """구간의 사이트(도메인)별 사용 시간(브라우저 상세 화면의 사이트 목록용).

        process 쿼리 파라미터가 어느 브라우저의 사용 시간인지 정한다.

        사이트 컬럼이 생기기 전의 옛 DB는 hub가 고치지 않고(읽기 전용) 빈 목록으로 답한다.
        """
        query = parse_qs(raw_query)
        try:
            start, end = _usage_bounds(query)
            process = query.get("process", [""])[0]
            if not process:
                raise ValueError("process가 필요합니다.")
        except ValueError as exc:
            self._send_json(
                400, api_error.error_body(api_error.INVALID_REQUEST, str(exc))
            )
            return

        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                payload = site_usage_by_range(conn, process, start, end)
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            if not _is_missing_site_schema(exc):
                logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
                self._send_json(
                    503,
                    api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
                )
                return
            payload = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "by_site": [],
            }
        except sqlite3.Error:
            logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
            self._send_json(
                503,
                api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
            )
            return

        self._send_json(200, payload)

    def _get_site_icon(self, domain: str) -> None:
        """도메인 → Chrome이 저장해 둔 아이콘 PNG.

        recorder가 기록한 도메인(sites 테이블)만 받는다 — 임의의 도메인에 대한 아이콘 조회가
        브라우저 기록을 더듬는 통로가 되지 않게 한다. UI가 아닌 페이지의 요청은 기록 여부를
        드러내지 않도록 똑같이 거부한다(is_trusted_page). 요청은 이 PC의 파일만 읽고 외부로
        나가지 않는다.
        """
        if not self._is_from_trusted_page():
            self._send_icon_denied()
            return
        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                known = conn.execute(
                    "SELECT 1 FROM sites WHERE domain = ?", (domain,)
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            if not _is_missing_site_schema(exc):
                logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
                self._send_json(
                    503,
                    api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
                )
                return
            known = None
        except sqlite3.Error:
            logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
            self._send_json(
                503,
                api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
            )
            return

        self._send_icon(
            self.site_icon_store.get(domain) if known else None,
            SITE_ICON_TTL_SECONDS,
        )

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
        차트가 15초마다 다시 그려져도 요청이 늘어나지 않는다. UI가 아닌 페이지의
        요청은 기록 여부를 드러내지 않도록 거부한다(is_trusted_page).
        """
        if not self._is_from_trusted_page():
            self._send_icon_denied()
            return
        try:
            conn = sqlite3.connect(f"{self.db_path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT exe_path FROM processes WHERE name = ?", (process_name,)
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            if "no such column: exe_path" not in str(exc):
                logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
                self._send_json(
                    503,
                    api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
                )
                return
            # 새 recorder가 컬럼을 추가하기 전의 옛 DB — hub는 읽기 전용이라 직접 고치지
            # 않고, 경로가 없는 것(아이콘 없음)으로 취급한다.
            row = None
        except sqlite3.Error:
            logger.exception("집계 DB를 읽지 못했습니다: %s", self.db_path)
            self._send_json(
                503,
                api_error.error_body(api_error.UNAVAILABLE, "database unavailable"),
            )
            return

        self._send_icon(
            self.icon_store.get(row[0]) if row and row[0] else None,
            _ICON_MAX_AGE_SECONDS,
        )

    def _is_from_trusted_page(self) -> bool:
        """이 요청이 우리 UI 페이지에서 온 것인지(Referer 기준 — is_trusted_page 참고)."""
        return is_trusted_page(self.headers.get("Referer", ""), self.allowed_origins)

    def _send_icon_denied(self) -> None:
        """UI가 아닌 곳의 아이콘 요청. "아이콘 없음"과 같은 모양의 404지만 캐시하지 않는다."""
        self._send_json(
            404,
            api_error.error_body(api_error.NOT_FOUND, "icon not found"),
            {"Cache-Control": "no-store"},
        )

    def _send_icon(self, icon: tuple[str, bytes] | None, max_age_seconds: int) -> None:
        """(키, PNG)를 캐시 헤더와 함께 보낸다. None이면 404(짧게 캐시)."""
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
            "Cache-Control": f"private, max-age={max_age_seconds}",
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

    def log_request(self, code: object = "-", size: object = "-") -> None:
        """요청 한 줄을 hub 로그에 남긴다: 메서드, 경로, 상태 코드만. 쿼리(이메일·세션 키)와 본문은 남기지 않는다."""
        logger.info("%s %s -> %s", self.command, loggable_path(urlsplit(self.path).path), code)

    def log_message(self, log_format: str, *args: object) -> None:
        pass  # 기본 동작(stderr에 접근 로그 출력)을 끈다.


def main() -> None:
    """CLI 인자(`--port`, `--db-path`)를 파싱해서 lock을 잡고 API 서버를 띄운다."""
    parser = argparse.ArgumentParser(description="whatever.log 집계 API 서버")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--goals-db-path", type=Path, default=DEFAULT_GOALS_DB_PATH)
    parser.add_argument("--sync-db-path", type=Path, default=DEFAULT_SYNC_DB_PATH, help="동기화 에이전트의 sync.db(이 PC의 기기 ID를 읽기 전용으로 확인한다)")
    parser.add_argument(
        "--allowed-origin",
        action="append",
        type=parse_origin,
        help="읽기·쓰기를 허용할 UI의 origin(여러 번 줄 수 있다). 주면 기본값(Vite dev server)을 대체한다.",
    )
    args = parser.parse_args()

    configure_logging(logger, DEFAULT_LOG_PATH)

    try:
        lock = acquire_lock(_lock_path_for_port(args.port))
    except AlreadyRunningError:
        logger.exception("시작하지 못했습니다.")
        sys.exit(EXIT_ALREADY_RUNNING)

    try:
        # 이전 실행이 비정상 종료하며 남긴 즐겨찾기 아이콘 복사본(방문 주소가 들어 있다)을 지운다.
        # 중복 실행 lock을 잡은 뒤, 이 프로세스가 작업 폴더를 만들기 전에 한 번만 한다.
        remove_stale_work_dirs(WORK_DIR_PREFIX)
        _Handler.db_path = args.db_path
        _Handler.goals_db_path = args.goals_db_path
        _Handler.sync_db_path = args.sync_db_path
        _Handler.allowed_origins = frozenset(args.allowed_origin or DEFAULT_ALLOWED_ORIGINS)
        logger.info("포트 %d에서 집계 API를 시작합니다. DB: %s", args.port, args.db_path)
        server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
        server.serve_forever()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
