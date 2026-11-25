// 새 버전 확인(docs/updates.md 1단계). hub가 하루 한 번 GitHub에 묻고 결과를 기억한다.

import { getJson, SHORT_REQUEST_TIMEOUT_MS, sendJson } from "./client";
import type { UpdateState } from "./types";

/** 지금 상태(확인할 때가 됐으면 hub가 GitHub에 묻는다). */
export function fetchUpdate(): Promise<UpdateState> {
  return getJson("/api/update", SHORT_REQUEST_TIMEOUT_MS);
}

/** 하루를 기다리지 않고 지금 묻는다. */
export function checkUpdateNow(): Promise<UpdateState> {
  return sendJson("POST", "/api/update/check", {}, SHORT_REQUEST_TIMEOUT_MS);
}

/** 그 버전의 알림 줄을 다시 보이지 않게 한다("나중에"). 더 새 버전이 나오면 다시 알린다. */
export function dismissUpdate(version: string): Promise<UpdateState> {
  return sendJson(
    "POST",
    "/api/update/settings",
    { dismissed: version },
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 새 버전 알림(확인)을 켜고 끈다. */
export function setUpdateEnabled(enabled: boolean): Promise<UpdateState> {
  return sendJson(
    "POST",
    "/api/update/settings",
    { enabled },
    SHORT_REQUEST_TIMEOUT_MS,
  );
}
