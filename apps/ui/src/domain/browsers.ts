/**
 * recorder가 사이트(도메인)를 기록하는 브라우저 프로세스. Python 쪽 표
 * (packages/chromium/src/chromium/browsers.py)와 같아야 한다 — 브라우저를 더하면 양쪽에
 * 같이 더한다. 이 목록의 프로세스 상세 화면에만 사이트 목록이 붙는다.
 */
export const BROWSER_PROCESSES: ReadonlySet<string> = new Set([
  "chrome.exe",
  "msedge.exe",
  "brave.exe",
  "vivaldi.exe",
]);

/** 이 프로세스가 사이트를 기록하는 브라우저인지. */
export function isBrowserProcess(process: string): boolean {
  return BROWSER_PROCESSES.has(process);
}
