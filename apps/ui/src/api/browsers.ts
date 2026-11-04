import { getJson } from "./client.ts";

// 어느 프로세스에 사이트 목록을 붙일지는 서버가 안다(recorder가 사이트를 기록하는 브라우저 표가
// 서버에 있다) — 화면이 자기 목록을 따로 들고 있으면 브라우저를 더할 때 양쪽이 어긋난다.
// 목록은 앱이 떠 있는 동안 바뀌지 않으니 한 번만 받아서 들고 있는다.
const REQUEST_TIMEOUT_MS = 10_000;

let browsers: Promise<ReadonlySet<string>> | null = null;

/**
 * 이 프로세스가 사이트(도메인)를 기록하는 브라우저인지. 목록을 못 받으면(hub가 아직 안 떴거나
 * 옛 hub) false로 보고 — 사이트 목록은 덤이라 없어도 화면이 동작해야 한다 — 실패는 기억하지
 * 않아 다음 호출에서 다시 받아 본다.
 */
export function isSiteTrackingBrowser(process: string): Promise<boolean> {
  browsers ??= getJson<{ browsers: string[] }>(
    "/api/browsers",
    REQUEST_TIMEOUT_MS,
  ).then((response) => new Set(response.browsers));
  const pending = browsers;
  return pending.then(
    (names) => names.has(process),
    () => {
      if (browsers === pending) {
        browsers = null;
      }
      return false;
    },
  );
}
