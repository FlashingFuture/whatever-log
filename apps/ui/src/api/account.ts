import { getJson, SHORT_REQUEST_TIMEOUT_MS, sendJson } from "./client.ts";
import type { AccountSnapshot, ExternalLink, LogoutResponse } from "./types";

/** 로그인 상태. 토큰은 받지 않는다(hub가 주지 않는다). */
export function fetchAccount(): Promise<AccountSnapshot> {
  return getJson("/api/account", SHORT_REQUEST_TIMEOUT_MS);
}

/**
 * 로그인을 시작한다. 시스템 브라우저에서 사용자가 끝낼 때까지 걸리므로 응답은 바로(진행 중 상태로) 오고,
 * 끝났는지는 `fetchAccount`를 다시 불러 확인한다.
 */
export function startLogin(provider: string): Promise<AccountSnapshot> {
  return sendJson(
    "POST",
    "/api/account/login",
    { provider },
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 진행 중인 로그인을 취소한다(진행 중이 아니어도 오류가 아니다). */
export function cancelLogin(): Promise<AccountSnapshot> {
  return sendJson(
    "DELETE",
    "/api/account/login",
    undefined,
    // 서버 폐기를 시도하는 로그아웃보다 짧아도 되지만, 같은 상수를 쓴다.
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 로그아웃한다(이 PC의 로그인 정보 삭제 + 서버 토큰 폐기 시도). */
export function logout(): Promise<LogoutResponse> {
  return sendJson(
    "POST",
    "/api/account/logout",
    undefined,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 이름으로 정한 바깥 링크를 시스템 브라우저로 연다(주소는 hub가 정한다). */
export async function openExternalLink(link: ExternalLink): Promise<void> {
  await sendJson("POST", "/api/links/open", { link }, SHORT_REQUEST_TIMEOUT_MS);
}
