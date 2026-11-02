/**
 * 프로세스 아이콘을 지금 요청해도 되는지에 대한 기억. DOM과 무관한 순수 상태라 시계를 주입해
 * 테스트한다.
 *
 * - missing: hub가 404(아이콘 없음)로 확인해 준 이름. 5분 동안은 요청 자체를 안 보낸다(hub가
 *   "없음"을 캐시하는 시간과 같다 — 그 뒤엔 recorder가 경로를 채웠을 수 있어 다시 시도).
 * - transient: 503·연결 오류처럼 일시적인 실패. 짧게(30초) 쉬었다가 다시 시도한다 — 차트를
 *   다시 그릴 때마다(15초) 실패하는 아이콘마다 요청이 쌓이지 않게 하면서, hub가 돌아오면
 *   금방 복구되게 한다. "없음"으로 굳히지는 않는다.
 *
 * 기록이 쌓이기만 하지 않도록, 새로 기록할 때 만료된 항목을 함께 지운다.
 */
export type IconStatus = "missing" | "transient";

export const MISSING_TTL_MS = 5 * 60 * 1000;
export const TRANSIENT_TTL_MS = 30 * 1000;

const TTL_MS: Record<IconStatus, number> = {
  missing: MISSING_TTL_MS,
  transient: TRANSIENT_TTL_MS,
};

export class IconStatusCache {
  private entries = new Map<string, { status: IconStatus; at: number }>();

  /** 아직 유효한 상태(만료됐으면 지우고 null). */
  statusOf(name: string, now: number): IconStatus | null {
    const entry = this.entries.get(name);
    if (!entry) {
      return null;
    }
    if (now - entry.at >= TTL_MS[entry.status]) {
      this.entries.delete(name);
      return null;
    }
    return entry.status;
  }

  /** 이 이름의 기록이 만료되기까지 남은 시간(기록이 없거나 이미 만료됐으면 null). */
  remainingMs(name: string, now: number): number | null {
    const entry = this.entries.get(name);
    if (!entry || this.statusOf(name, now) === null) {
      return null;
    }
    return TTL_MS[entry.status] - (now - entry.at);
  }

  /** 아이콘이 실제로 불러와졌으면 앞선 실패 기록은 더 이상 맞지 않는다. */
  clear(name: string): void {
    this.entries.delete(name);
  }

  record(name: string, status: IconStatus, now: number): void {
    this.prune(now);
    this.entries.set(name, { status, at: now });
  }

  get size(): number {
    return this.entries.size;
  }

  private prune(now: number): void {
    for (const [name, entry] of this.entries) {
      if (now - entry.at >= TTL_MS[entry.status]) {
        this.entries.delete(name);
      }
    }
  }
}
