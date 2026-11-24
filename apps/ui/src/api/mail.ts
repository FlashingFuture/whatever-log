// 보고서 메일 구독(hub가 서버에 중개한다 — docs/mail-design.md). 목표는 이 PC의 목표 id로 주고받는다.

import { getJson, SHORT_REQUEST_TIMEOUT_MS, sendJson } from "./client";
import type {
  MailSubscriptionInput,
  MailSubscriptionSaved,
  MailSubscriptionState,
  MailSubscriptionView,
  TestMailResult,
} from "./types";

/** 구독(없으면 null)과 매일 구독 가능 여부. 로그인하지 않았으면 409, 로그인 기능이 없으면 503(ApiError). */
export function fetchMailSubscription(): Promise<MailSubscriptionState> {
  return getJson("/api/mail/subscription", SHORT_REQUEST_TIMEOUT_MS);
}

/**
 * 신청·변경. 다른 목표를 구독 중이면 409 `subscription_exists` — 사용자에게 묻고 `replace: true`로 다시 보낸다. 목표가 서버와 연결되지 않았으면
 * 409 `goal_not_synced`, 매일 상한이면 409 `daily_full`.
 */
export function saveMailSubscription(
  input: MailSubscriptionInput,
): Promise<MailSubscriptionSaved> {
  return sendJson(
    "PUT",
    "/api/mail/subscription",
    input,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 켜고 끈다. */
export async function setMailSubscriptionStatus(
  status: "active" | "paused",
): Promise<MailSubscriptionView> {
  const response = await sendJson<{ subscription: MailSubscriptionView }>(
    "POST",
    "/api/mail/subscription/status",
    { status },
    SHORT_REQUEST_TIMEOUT_MS,
  );
  return response.subscription;
}

/** 그만 받는다(신청한 것이 없어도 성공). */
export async function deleteMailSubscription(): Promise<void> {
  await sendJson(
    "DELETE",
    "/api/mail/subscription",
    undefined,
    SHORT_REQUEST_TIMEOUT_MS,
  );
}

/** 로그인한 계정의 주소로 시험 메일을 보낸다(하루 몇 통까지). */
export function sendTestMail(): Promise<TestMailResult> {
  return sendJson("POST", "/api/mail/test", {}, SHORT_REQUEST_TIMEOUT_MS);
}
