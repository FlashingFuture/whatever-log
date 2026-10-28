export interface ProcessUsage {
  process: string;
  active_seconds: number;
  idle_seconds: number;
  background_seconds: number;
  total_seconds: number;
}

export interface RangeUsage {
  start: string;
  end: string;
  by_process: ProcessUsage[];
}

// apps/hub가 고정 포트로 뜬다(apps/desktop이 자식 프로세스로 띄움).
const HUB_URL = "http://127.0.0.1:8787";

export function fetchUsage(range = "24h"): Promise<RangeUsage> {
  return fetch(`${HUB_URL}/api/usage?range=${range}`).then((response) => {
    // fetch()는 HTTP 상태와 무관하게 resolve된다 — hub가 DB를 못 읽어 503을
    // 주면 { "error": ... } 모양이라, 체크 없이 바로 RangeUsage로 취급하면
    // 렌더링이 undefined 필드에서 깨진다.
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json() as Promise<RangeUsage>;
  });
}
