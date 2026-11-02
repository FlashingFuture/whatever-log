import type { ProcessUsage } from "./api";

export interface UsageSummary {
  /** 집중(active) 시간의 합 — 한 순간에 하나뿐이라 합이 실제로 쓴 시간이다. */
  activeSeconds: number;
  idleSeconds: number;
  /** 집중 시간이 가장 긴 프로세스(집중 시간이 전부 0이면 null). */
  top: ProcessUsage | null;
}

/**
 * 구간의 요약. 프로세스는 겹쳐서 떠 있을 수 있어 전체(total)를 더하면 구간 길이를
 * 넘으므로 집중 시간 기준으로 합친다. 순서에 기대지 않고 직접 가장 큰 것을 찾는다 —
 * 동률이면 앞선(서버 정렬상 전체 시간이 길고 이름이 빠른) 쪽.
 */
export function summarizeUsage(byProcess: ProcessUsage[]): UsageSummary {
  let top: ProcessUsage | null = null;
  let activeSeconds = 0;
  let idleSeconds = 0;
  for (const row of byProcess) {
    activeSeconds += row.active_seconds;
    idleSeconds += row.idle_seconds;
    if (row.active_seconds > (top?.active_seconds ?? 0)) {
      top = row;
    }
  }
  return { activeSeconds, idleSeconds, top };
}
