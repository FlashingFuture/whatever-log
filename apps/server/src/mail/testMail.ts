import type { Db } from "../db.ts";
import { LIMITS, type Sender } from "./config.ts";
import type { MailPort } from "./port.ts";
import { recordSent, releaseSend, reserveSend, userKey } from "./quota.ts";

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
 *
 * - **계정을 지워도 한도는 이어진다:** 사용자별 횟수는 계정(`users.id`)이 아니라 Google 계정 고유 값의 해시(`userKey`)로 센다. 계정 삭제는 이 기록을 지우지 않고
 *   재로그인해도 같은 키라, "발송 → 삭제 → 재로그인"으로 한도를 되돌릴 수 없다. 서버 전체 횟수도 줄지 않는다.
 * - **자리를 돌려주는 때:** 서비스가 **접수하지 않았음이 확실한** 실패(키 오류, 거절, 한도)만 자리를 돌려준다. `unavailable`(5xx·네트워크·시간 초과·접수 번호 없음)은
 *   서비스가 이미 접수했을 수 있어서 자리를 **유지한다** — 돌려주면 재시도가 새 멱등 키로 같은 메일을 한 번 더 보내 실제 발송이 한도를 넘을 수 있다.
 */
// 사용자 키·발송 기록 보관 기간은 quota.ts가 갖는다(확인 메일·보고서와 같은 규칙). 예전 위치에서 가져다 쓰는 곳을 위해 다시 내보낸다.
export { RETENTION_DAYS, userKey } from "./quota.ts";

export async function sendTestMail(
  db: Db,
  userId: number,
  mail: MailDeps,
  now: Date,
): Promise<TestMailResult> {
  const user = await db
    .prepare("SELECT email, google_sub FROM users WHERE id = ?")
    .bind(userId)
    .first<{ email: string; google_sub: string }>();
  if (!user) {
    return {
      ok: false,
      status: 401,
      code: "invalid_token",
      message: "로그인이 필요합니다. 다시 로그인해 주세요.",
    };
  }

  const key = await userKey(user.google_sub);
  const reserved = await reserveSend(db, {
    key,
    kind: "test",
    perUserPerDay: LIMITS.testPerUserPerDay,
    now,
  });
  if (!reserved.ok) {
    return {
      ok: false,
      status: 429,
      code: reserved.personal ? "daily_limit" : "service_daily_limit",
      message: reserved.personal
        ? `시험 메일은 하루에 ${LIMITS.testPerUserPerDay}통까지 보낼 수 있어요. 내일 다시 시도해 주세요.`
        : "오늘 서버가 보낼 수 있는 메일을 모두 보냈어요. 내일 다시 시도해 주세요.",
    };
  }
  const { token } = reserved;

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
    await recordSent(db, token, result.id);
    return { ok: true, mode: mail.sender.mode, to: maskEmail(user.email) };
  }

  // 접수되지 않았음이 확실한 실패만 자리를 돌려준다. unavailable은 접수됐을 수 있어 유지한다(위 설명).
  if (result.reason !== "unavailable") {
    await releaseSend(db, token);
  }
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
        message:
          "메일 서비스의 응답을 확인하지 못했어요. 메일이 이미 갔을 수 있으니 받은편지함을 확인하고, 오지 않으면 잠시 뒤 다시 시도해 주세요.",
      };
  }
}
