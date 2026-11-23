import type { Db } from "../db.ts";
import { errorResponse, jsonResponse, readLimited } from "../http.ts";
import { type SuppressionReason, suppress } from "./suppression.ts";

/**
 * Resend 웹훅(`POST /mail/webhooks/resend`): 반송·스팸 신고가 오면 그 주소를 보내지 않을 목록에 넣는다. 스팸 신고와 영구 반송은 새 도메인의 평판을
 * 바로 깎으므로, 다음 보고서를 보내기 전에 막는다.
 *
 * 인증: Resend는 Svix 형식으로 서명한다 — `svix-id`·`svix-timestamp`·`svix-signature` 헤더, 서명 대상은 `${id}.${timestamp}.${본문}`,
 * 키는 `whsec_` 뒤의 base64를 푼 바이트, HMAC-SHA256. 서명이 없거나 틀리거나 5분보다 오래된 요청은 401이다(재전송 공격 방지).
 * 비밀(`RESEND_WEBHOOK_SECRET`)은 Resend 대시보드의 웹훅 설정에서 받아 `wrangler secret put`으로 넣는다.
 */

const MAX_BODY_BYTES = 64 * 1024;
const TOLERANCE_SECONDS = 5 * 60;
const encoder = new TextEncoder();

function decodeBase64(text: string): Uint8Array | null {
  try {
    return Uint8Array.from(atob(text), (char) => char.charCodeAt(0));
  } catch {
    return null;
  }
}

/** Svix 서명 확인. 헤더의 서명 중 하나라도 맞으면 통과(비밀을 바꾸는 동안 둘이 올 수 있다). 비교는 `crypto.subtle.verify`가 한다. */
export async function verifySvix(
  secret: string,
  headers: Headers,
  body: string,
  nowSeconds: number,
): Promise<boolean> {
  const id = headers.get("svix-id");
  const timestamp = headers.get("svix-timestamp");
  const signatures = headers.get("svix-signature");
  if (!id || !timestamp || !signatures || !/^\d{1,12}$/.test(timestamp)) {
    return false;
  }
  if (Math.abs(nowSeconds - Number(timestamp)) > TOLERANCE_SECONDS) {
    return false;
  }
  const keyBytes = decodeBase64(secret.replace(/^whsec_/, ""));
  if (!keyBytes || keyBytes.length === 0) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const signed = encoder.encode(`${id}.${timestamp}.${body}`);
  for (const part of signatures.split(" ")) {
    const [version, value] = part.split(",", 2);
    if (version !== "v1" || !value) continue;
    const bytes = decodeBase64(value);
    if (bytes && (await crypto.subtle.verify("HMAC", key, bytes, signed))) {
      return true;
    }
  }
  return false;
}

/** `"이름 <a@b.c>"` 또는 `"a@b.c"`에서 주소만. */
function address(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /<([^<>]+)>/.exec(value);
  const text = (match ? match[1] : value).trim();
  return /^[^\s@]+@[^\s@]+$/.test(text) ? text : null;
}

/** 이벤트에서 막을 사유. 일시적 반송(받은편지함 가득 참 등)은 막지 않는다 — 다음에는 갈 수 있다. */
function reasonOf(event: Record<string, unknown>): SuppressionReason | null {
  if (event.type === "email.complained") return "complained";
  if (event.type !== "email.bounced") return null;
  const data = event.data as Record<string, unknown> | undefined;
  const bounce = data?.bounce as Record<string, unknown> | undefined;
  const kind = typeof bounce?.type === "string" ? bounce.type : "";
  return /transient|temporary|soft/i.test(kind) ? null : "bounced";
}

export async function handleResendWebhook(
  request: Request,
  deps: { db: Db; secret: string | undefined; now: () => Date },
): Promise<Response> {
  if (request.method !== "POST") {
    return errorResponse(405, "method_not_allowed", "POST만 받습니다.", {
      Allow: "POST",
    });
  }
  if (!deps.secret) {
    console.warn("mail config: RESEND_WEBHOOK_SECRET이 설정되지 않았습니다.");
    return errorResponse(503, "not_configured", "웹훅이 설정되지 않았습니다.");
  }
  const raw = await readLimited(request, MAX_BODY_BYTES);
  if (raw === null) {
    return errorResponse(413, "invalid_request", "본문이 너무 큽니다.");
  }
  const body = new TextDecoder().decode(raw);
  const now = deps.now();
  if (
    !(await verifySvix(
      deps.secret,
      request.headers,
      body,
      Math.floor(now.getTime() / 1000),
    ))
  ) {
    return errorResponse(401, "invalid_signature", "서명이 올바르지 않습니다.");
  }
  let event: Record<string, unknown>;
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed !== "object" || parsed === null) throw new Error();
    event = parsed as Record<string, unknown>;
  } catch {
    return errorResponse(
      400,
      "invalid_request",
      "본문이 올바른 JSON이 아닙니다.",
    );
  }
  const reason = reasonOf(event);
  if (reason) {
    const data = event.data as Record<string, unknown> | undefined;
    const recipients = Array.isArray(data?.to) ? data.to : [data?.to];
    for (const value of recipients) {
      const email = address(value);
      if (email) await suppress(deps.db, email, reason, now);
    }
    // 주소는 로그에 남기지 않는다(사유와 수만).
    console.log(`mail suppression: ${reason} x${recipients.length}`);
  }
  // 모르는 이벤트도 200 — 다시 보내지 않게(우리가 처리하지 않는 종류다).
  return jsonResponse({ ok: true });
}
