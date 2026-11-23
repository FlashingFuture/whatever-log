import type { Db } from "../db.ts";
import { LIMITS } from "./config.ts";
import {
  type LinkConfig,
  unsubscribeHeaders,
  unsubscribeUrl,
} from "./links.ts";
import { recordSent, releaseSend, reserveSend, userKey } from "./quota.ts";
import type { SubscriptionRow } from "./subscriptions.ts";
import { isSuppressed } from "./suppression.ts";
import type { MailDeps } from "./testMail.ts";

/**
 * 첫 신청 확인 메일의 결과:
 * - `sent`: 보냈다 / `already`: 이 사용자(Google 계정)는 이미 받았다 / `suppressed`: 보내지 않을 주소다
 * - `not_configured`: 메일이나 수신 거부 링크 설정이 없다 / `limited`: 오늘 한도에 닿았다 / `failed`: 서비스가 보내지 못했다
 * 보내지 못했어도 구독은 그대로다 — 다음 신청·변경 때 다시 시도한다(같은 구독이면 같은 멱등 키라 이미 접수된 메일이 두 번 가지 않는다).
 */
export type WelcomeOutcome =
  | "sent"
  | "already"
  | "suppressed"
  | "not_configured"
  | "limited"
  | "failed";

const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

/** 일정을 한 줄로: "매일 09:00", "매주 월요일 09:00", "매월 1일 09:00" (시간대). */
export function describeSchedule(row: SubscriptionRow): string {
  const when =
    row.frequency === "daily"
      ? "매일"
      : row.frequency === "weekly"
        ? `매주 ${WEEKDAYS[row.weekday ?? 0]}요일`
        : `매월 ${row.day_of_month}일`;
  return `${when} ${row.send_time} (${row.timezone})`;
}

const PERIOD_OF = {
  daily: "전날 하루",
  weekly: "지난주(월~일)",
  monthly: "지난달",
} as const;

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

/**
 * 첫 신청 확인 메일을 보낸다(안내형 — 이메일은 Google로 이미 확인됐으므로 이중 확인 링크는 없다). "첫 신청"은 **Google 계정 단위로 한 번**이다:
 * `mail_welcomes`(계정과 무관한 키)에 있으면 보내지 않는다 — 신청·해지·계정 삭제를 되풀이해 메일 폭탄을 만들지 못하게.
 * 발송은 시험 메일과 같은 한도(서버 전체 하루 상한)를 쓰고, 멱등 키는 구독 id로 정한다.
 */
export async function sendWelcome(
  db: Db,
  user: { email: string; googleSub: string },
  subscription: SubscriptionRow,
  goalName: string,
  mail: (MailDeps & { links?: LinkConfig }) | null,
  now: Date,
): Promise<WelcomeOutcome> {
  const key = await userKey(user.googleSub);
  const welcomed = await db
    .prepare("SELECT 1 AS present FROM mail_welcomes WHERE user_key = ?")
    .bind(key)
    .first();
  if (welcomed) return "already";
  if (await isSuppressed(db, user.email)) return "suppressed";
  if (!mail?.links) return "not_configured";

  const reserved = await reserveSend(db, {
    key,
    kind: "welcome",
    perUserPerDay: LIMITS.welcomePerUserPerDay,
    now,
  });
  if (!reserved.ok) return "limited";

  const link = await unsubscribeUrl(mail.links, subscription.id);
  const lines = [
    `"${goalName}" 목표의 보고서 메일을 신청했어요.`,
    `일정: ${describeSchedule(subscription)} — ${PERIOD_OF[subscription.frequency]}의 달성도를 보내요.`,
    "달성도는 PC의 동기화가 서버에 올린 값이라, PC가 꺼져 있던 날은 늦게 반영될 수 있어요.",
    "보고서는 앱의 목표 화면에서 끄거나 바꿀 수 있어요.",
  ];
  const result = await mail.port.send({
    from: mail.sender.from,
    to: user.email,
    subject: "[whatever.log] 보고서 메일을 신청했어요",
    text: [...lines, "", `더 받지 않으려면: ${link}`].join("\n"),
    html:
      lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("") +
      `<p><a href="${escapeHtml(link)}">더 받지 않기</a></p>`,
    idempotencyKey: `welcome-${subscription.id}`,
    headers: unsubscribeHeaders(link),
  });
  if (result.ok) {
    await recordSent(db, reserved.token, result.id);
    await db
      .prepare(
        "INSERT INTO mail_welcomes (user_key, welcomed_at) VALUES (?, ?) ON CONFLICT(user_key) DO NOTHING",
      )
      .bind(key, now.toISOString())
      .run();
    return "sent";
  }
  // 접수되지 않았음이 확실한 실패만 자리를 돌려준다(접수됐을 수 있으면 같은 멱등 키로 다시 보낼 때 서비스가 한 번만 보낸다).
  if (result.reason !== "unavailable") {
    await releaseSend(db, reserved.token);
  }
  console.warn(`welcome mail failed: ${result.reason} ${result.detail ?? ""}`);
  return "failed";
}
