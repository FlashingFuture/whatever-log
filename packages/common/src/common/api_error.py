"""로컬 HTTP API(apps/hub 등)의 에러 응답 형식.

모든 4xx/5xx 응답 본문은 이 모양이다::

    {"error": {"code": "invalid_request", "message": "start와 end가 모두 필요합니다."}}

- code: 클라이언트가 분기·번역에 쓰는 안정적인 식별자(아래 상수). 문구가 바뀌어도
  유지된다.
- message: 사람이 읽는 설명. 내부 경로·스택은 싣지 않는다(로그에만 남긴다).

어떤 엔드포인트에서만 쓰는 코드는 여기 추가하지 않고 그 앱에서 정의한다. 이
형식을 쓰는 클라이언트(apps/ui/src/api.ts)는 다른 언어라 같은 모양을 따로
선언해 둔다 — 형식을 바꾸면 양쪽을 같이 고친다.
"""

from typing import TypedDict

INVALID_REQUEST = "invalid_request"  # 4xx: 입력이 잘못됨(고쳐서 다시 보내야 함)
NOT_FOUND = "not_found"  # 404
UNAVAILABLE = "unavailable"  # 503: 서버 쪽 사정(DB 등)으로 지금은 못 함
INTERNAL = "internal"  # 500: 예상 못 한 오류


class ErrorDetail(TypedDict):
    code: str
    message: str


class ErrorBody(TypedDict):
    error: ErrorDetail


def error_body(code: str, message: str) -> ErrorBody:
    return {"error": {"code": code, "message": message}}
