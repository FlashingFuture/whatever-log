import type { Db } from "../db.ts";
import { LIMITS, type Sender } from "./config.ts";
import type { MailPort } from "./port.ts";

export interface MailDeps {
  port: MailPort;
  sender: Sender;
}

export type TestMailResult =
  | { ok: true; mode: Sender["mode"]; to: string }
  | { ok: false; status: number; code: string; message: string };

/** `person@example.com` → `p***@example.com`. 응답·로그에 전체 주소를 싣지 않는다. */
export function maskEmail(email: string): string {
  const at = email.lastIndexOf("@");
  if (at <= 0) return "***";
  return `${email[0]}***${email.slice(at)}`;
}

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

const BODY_LINES = [
  "whatever.log 서버에서 보낸 시험 메일이에요.",
  "이 메일이 보인다면 보고서 메일을 받을 준비가 된 거예요.",
  "요청한 적이 없다면 무시하셔도 돼요. 계정이나 데이터는 바뀌지 않아요.",
];

/**
 * 로그인한 사용자 본인에게 시험 메일을 한 통 보낸다. **수신자는 서버가 아는 계정 이메일뿐이다** — 요청에서 주소를 받지 않아
 * 우리 도메인으로 아무에게나 보내는 스팸 중계가 되지 않는다.
 *
 * 한도(사용자별·서버 전체 일일 상한)는 "확인 + 자리 잡기"를 한 문장으로 해서(동시에 요청이 몰려도 넘지 않는다) 먼저 통과해야 보낸다.
 * 발송에 실패하면 잡은 자리를 돌려준다(실패가 한도를 깎지 않는다).
 */
export async function sendTestMail(
  db: Db,
  userId: number,
  mail: MailDeps,
  now: Date,
): Promise<TestMailResult> {
  const user = await db
    .prepare("SELECT email FROM users WHERE id = ?")
    .bind(userId)
    .first<{ email: string }>();
  if (!user) {
    return {
      ok: false,
      status: 401,
      code: "invalid_token",
      message: "로그인이 필요합니다. 다시 로그인해 주세요.",
    };
  }

  const day = now.toISOString().slice(0, 10);
  const token = crypto.randomUUID();
  const reserved = await db
    .prepare(
      `INSERT INTO mail_sends (user_id, kind, sent_on, token, created_at)
       SELECT ?1, 'test', ?2, ?3, ?4
       WHERE (SELECT COUNT(*) FROM mail_sends WHERE sent_on = ?2) < ?5
         AND (SELECT COUNT(*) FROM mail_sends WHERE sent_on = ?2 AND user_id = ?1 AND kind = 'test') < ?6`,
    )
    .bind(
      userId,
      day,
      token,
      now.toISOString(),
      LIMITS.perDayTotal,
      LIMITS.testPerUserPerDay,
    )
    .run();
  if (reserved.meta.changes === 0) {
    const mine = await db
      .prepare(
        "SELECT COUNT(*) AS n FROM mail_sends WHERE sent_on = ? AND user_id = ? AND kind = 'test'",
      )
      .bind(day, userId)
      .first<{ n: number }>();
    const personal = (mine?.n ?? 0) >= LIMITS.testPerUserPerDay;
    return {
      ok: false,
      status: 429,
      code: personal ? "daily_limit" : "service_daily_limit",
      message: personal
        ? `시험 메일은 하루에 ${LIMITS.testPerUserPerDay}통까지 보낼 수 있어요. 내일 다시 시도해 주세요.`
        : "오늘 서버가 보낼 수 있는 메일을 모두 보냈어요. 내일 다시 시도해 주세요.",
    };
  }

  const stamp = `보낸 시각: ${now.toISOString()}`;
  const result = await mail.port.send({
    from: mail.sender.from,
    to: user.email,
    subject: "[whatever.log] 시험 메일",
    text: [...BODY_LINES, "", stamp].join("\n"),
    html: `${BODY_LINES.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}<p>${escapeHtml(stamp)}</p>`,
    idempotencyKey: `test-${token}`,
  });

  if (result.ok) {
    await db
      .prepare("UPDATE mail_sends SET provider_id = ? WHERE token = ?")
      .bind(result.id, token)
      .run();
    return { ok: true, mode: mail.sender.mode, to: maskEmail(user.email) };
  }

  await db.prepare("DELETE FROM mail_sends WHERE token = ?").bind(token).run();
  switch (result.reason) {
    case "unauthorized":
      return {
        ok: false,
        status: 502,
        code: "mail_not_configured",
        message: "메일 서비스 키가 올바르지 않아요. 서버 설정을 확인해 주세요.",
      };
    case "rejected":
      return {
        ok: false,
        status: 502,
        code: "mail_rejected",
        message:
          mail.sender.mode === "sandbox"
            ? "발신 도메인이 아직 설정되지 않아, 메일 서비스에 가입한 계정의 주소로만 보낼 수 있어요."
            : "메일 서비스가 이 메일을 받아 주지 않았어요. 발신 도메인 인증 상태를 확인해 주세요.",
      };
    case "rate_limited":
      return {
        ok: false,
        status: 429,
        code: "provider_rate_limited",
        message: "메일 서비스의 한도에 닿았어요. 잠시 뒤 다시 시도해 주세요.",
      };
    case "unavailable":
      return {
        ok: false,
        status: 503,
        code: "mail_unavailable",
        message: "메일 서비스에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
      };
  }
}
