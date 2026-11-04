import { HUB_URL } from "./client";

/**
 * 프로세스 아이콘 URL. 이름만 넘기고 경로는 hub가 DB에서 찾는다. 브라우저가
 * hub의 Cache-Control/ETag로 캐싱하므로 같은 URL은 다시 받지 않는다.
 */
export function iconUrl(processName: string): string {
  return `${HUB_URL}/api/icons/${encodeURIComponent(processName)}`;
}

/** 사이트(도메인) 아이콘 URL. hub가 브라우저가 저장해 둔 아이콘을 돌려준다(외부 요청 없음). */
export function siteIconUrl(domain: string): string {
  return `${HUB_URL}/api/site-icons/${encodeURIComponent(domain)}`;
}
