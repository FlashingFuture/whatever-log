/**
 * 서버 API 계약 번호. 클라이언트(앱)가 기대하는 요청·응답의 모양이 바뀔 때마다 1씩 올린다 — 칸을 더하는 호환 변경이어도 새 앱이 그 칸에 기대면 올린다.
 * 앱 출시 워크플로가 운영 서버의 `GET /version`으로 이 값을 확인해, 운영 서버가 앱보다 뒤처진 채로 앱이 나가지 않게 한다(docs/deploy.md).
 * 앱이 요구하는 번호는 `packages/cloud/src/cloud/compat.py`의 `REQUIRED_SERVER_API`다.
 *
 * 1: 로그인, 목표·달성도 동기화, 기기, 계정 삭제, 시험 메일
 * 2: 목표 기간(`start_date`·`end_date`), `POST /progress/remove`
 * 3: 보고서 메일 구독(`GET·PUT·PATCH·DELETE /mail/subscription`) — 앱(hub)이 쓰기 시작했다
 */
export const API_VERSION = 3;
