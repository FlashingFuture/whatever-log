/**
 * 화면에서 가리키는 바깥 주소. 평소에는 hub가 이름("privacy")으로 시스템 브라우저를 열어 주고(네이티브 창에서는
 * 링크가 기본 브라우저로 열리지 않을 수 있다), hub에 닿지 못할 때만 이 주소로 직접 연다.
 * 주소의 원본은 apps/hub/src/hub/external_links.py의 LINKS다 — 바꾸면 양쪽을 같이 고친다.
 */
export const PRIVACY_DOC_URL =
  "https://github.com/FlashingFuture/whatever-log/blob/main/docs/data-handling.md";
