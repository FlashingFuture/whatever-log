"""로컬 HTTP API(apps/hub 등)의 에러 응답 형식.

모든 4xx/5xx 응답 본문은 이 모양이다::

    {"error": {"code": "invalid_request", "message": "start와 end가 모두 필요합니다."}}

- code: 클라이언트가 분기·번역에 쓰는 안정적인 식별자(아래 상수). 문구가 바뀌어도
  유지된다.
- message: 사람이 읽는 설명. 내부 경로·스택은 싣지 않는다(로그에만 남긴다).
- fields(선택): 입력 오류가 어느 칸에서 났는지 칸별로 알리는 목록
  `[{"field": "name", "code": "length", "message": "..."}]`. 화면이 칸 옆에 그대로 보여 준다.

어떤 엔드포인트에서만 쓰는 코드는 여기 추가하지 않고 그 앱에서 정의한다. 이
형식을 쓰는 클라이언트(apps/ui/src/api/client.ts)는 다른 언어라 같은 모양을 따로
선언해 둔다 — 형식을 바꾸면 양쪽을 같이 고친다.
"""

from typing import NotRequired, TypedDict

INVALID_REQUEST = "invalid_request"  # 4xx: 입력이 잘못됨(고쳐서 다시 보내야 함)
FORBIDDEN = "forbidden"  # 403: 허용되지 않은 출처·호스트의 요청
NOT_FOUND = "not_found"  # 404
UNAVAILABLE = "unavailable"  # 503: 서버 쪽 사정(DB 등)으로 지금은 못 함
INTERNAL = "internal"  # 500: 예상 못 한 오류


class FieldErrorDetail(TypedDict):
    """입력 한 칸의 오류."""

    field: str
    code: str
    message: str


class ErrorDetail(TypedDict):
    """응답 본문의 error 객체."""

    code: str
    message: str
    fields: NotRequired[list[FieldErrorDetail]]


class ErrorBody(TypedDict):
    """에러 응답 본문 전체."""

    error: ErrorDetail


def error_body(code: str, message: str, fields: list[FieldErrorDetail] | None = None) -> ErrorBody:
    """에러 응답 본문을 만든다. 입력 오류면 fields에 칸별 오류를 싣는다."""
    detail: ErrorDetail = {"code": code, "message": message}
    if fields is not None:
        detail["fields"] = fields
    return {"error": detail}
