"""이 앱이 서버에 요구하는 API 계약 번호.

서버의 `API_VERSION`(apps/server/src/version.ts)이 이 값보다 작으면, 이 앱이 보내는 요청이나 기대하는 응답을 서버가 모른다
(예: 기간 칸을 모르는 서버 — 2026-11-23에 앱이 서버보다 먼저 나가 동기화가 `bad_response`로 멈췄다). 앱 출시 워크플로가 운영 서버의
`GET /version`을 이 값과 견줘, 서버가 뒤처졌으면 출시를 멈춘다(scripts/check_server_api.py, docs/deploy.md).

새 앱이 서버의 새 칸·새 주소에 기대게 되면 서버의 `API_VERSION`을 올리고, 이 값도 같이 올린다.
"""

REQUIRED_SERVER_API = 2
