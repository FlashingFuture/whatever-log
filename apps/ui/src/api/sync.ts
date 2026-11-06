import { getJson, sendJson } from "./client.ts";
import type { SyncPlan, SyncResult } from "./types";

// hub가 서버(Cloudflare)를 한 번 부르고 DB를 쓰므로, 로컬 조회보다 넉넉하게 기다린다.
const SYNC_TIMEOUT_MS = 30_000;

/** 로그인 직후 확인 창의 계획: 서버의 목표와 이 PC의 목표를 견준 항목들. 서버에 닿지 못하면 ApiError(503)다. */
export function fetchSyncPlan(): Promise<SyncPlan> {
  return getJson("/api/sync/plan", SYNC_TIMEOUT_MS);
}

/** 사용자가 체크한 항목(key)을 적용한다. 체크하지 않은 이 PC 목표는 서버에 올라가지 않는다. */
export function applySync(accepted: readonly string[]): Promise<SyncResult> {
  return sendJson("POST", "/api/sync/apply", { accepted }, SYNC_TIMEOUT_MS);
}
