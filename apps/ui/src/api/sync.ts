import { getJson, SHORT_REQUEST_TIMEOUT_MS, sendJson } from "./client.ts";
import type {
  DeleteAccountResult,
  DeviceList,
  SyncPlan,
  SyncResult,
  SyncStatus,
} from "./types";

// hub가 서버(Cloudflare)를 한 번 부르고 DB를 쓰므로, 로컬 조회보다 넉넉하게 기다린다.
const SYNC_TIMEOUT_MS = 30_000;
// 계정 삭제는 hub가 취소한 로그인이 끝나기를 최대 30초 기다린 뒤 서버를 부른다(그 호출도 최대 수십 초). 그 합보다 길게 기다려야
// 삭제가 끝났는데 화면만 먼저 시간 초과로 끊기지 않는다.
const DELETE_ACCOUNT_TIMEOUT_MS = 90_000;

/** 로그인 직후 확인 창의 계획: 서버의 목표와 이 PC의 목표를 견준 항목들. 서버에 닿지 못하면 ApiError(503)다. */
export function fetchSyncPlan(): Promise<SyncPlan> {
  return getJson("/api/sync/plan", SYNC_TIMEOUT_MS);
}

/**
 * 사용자가 체크한 항목(key)을 적용한다. 체크하지 않은 이 PC 목표는 서버에 올라가지 않는다. email은 확인 창을 열었을 때의
 * 계정(`SyncPlan.email`)이고, 그 사이 다른 계정으로 로그인했다면 hub가 적용하지 않고 거절한다.
 */
export function applySync(
  accepted: readonly string[],
  email: string | null,
  session: string | null,
): Promise<SyncResult> {
  return sendJson(
    "POST",
    "/api/sync/apply",
    { accepted, email, session },
    SYNC_TIMEOUT_MS,
  );
}

/** 동기화 상태. 이 PC의 설정과 에이전트가 적은 기록만 읽고 서버를 부르지 않는다. */
export function fetchSyncStatus(): Promise<SyncStatus> {
  return getJson("/api/sync/status", SHORT_REQUEST_TIMEOUT_MS);
}

/** 달성도를 보낸 기기들(서버에서 받는다)과, 목록을 받은 계정. */
export function fetchDevices(): Promise<DeviceList> {
  return getJson("/api/devices", SYNC_TIMEOUT_MS);
}

/**
 * 기기가 보낸 달성 기록을 서버에서 지운다. email은 목록을 받았을 때의 계정이고, 지금 로그인한 계정과 다르면 hub가 거절한다
 * (계정 A의 목록에서 누른 삭제가 B의 기록을 지우지 않게). 이 PC의 기기도 hub가 거절한다.
 */
export async function deleteDevice(
  deviceId: string,
  email: string | null,
  session: string | null,
): Promise<void> {
  await sendJson(
    "DELETE",
    `/api/devices/${encodeURIComponent(deviceId)}?${new URLSearchParams({ email: email ?? "", session: session ?? "" })}`,
    undefined,
    SYNC_TIMEOUT_MS,
  );
}

/**
 * 서버의 계정과 모든 데이터를 지운다(되돌릴 수 없다). email은 사용자가 확인한 계정이고, 지금 로그인한 계정과 다르면 hub가 거절한다.
 * 서버 삭제에 성공한 뒤에만 이 PC의 로그인·동기화 연결이 정리된다.
 */
export function deleteAccount(
  email: string | null,
  session: string | null,
): Promise<DeleteAccountResult> {
  return sendJson(
    "POST",
    "/api/account/delete",
    { email, session },
    DELETE_ACCOUNT_TIMEOUT_MS,
  );
}
