import type { Db } from "../db.ts";
import { LIMITS } from "./config.ts";

/** 발송 기록을 이 기간(일)만 남긴다. 한도는 오늘 기록만 세므로 그 이상 보관할 이유가 없다 — 해시라도 필요 이상 오래 남기지 않는다. */
export const RETENTION_DAYS = 2;

export type SendKind = "test" | "report" | "welcome";

export type Reservation =
  | { ok: true; token: string }
  | {
      ok: false;
      /** 이 사용자의 이 종류 한도에 닿았다(true) / 서버 전체 한도에 닿았다(false). */
      personal: boolean;
    };

/**
 * 계정과 무관한 사용자 키: Google 계정 고유 값(sub)의 SHA-256(16진 64자). 원문을 남기지 않고, 같은 Google 계정이면 삭제·재로그인 뒤에도 같다.
 * 접두사 `mail:`로 이 용도의 해시를 다른 곳의 해시와 구분한다.
 */
export async function userKey(googleSub: string): Promise<string> {
  return sha256Hex(`mail:${googleSub}`);
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * 발송 자리를 하나 잡는다: 서버 전체 하루 상한과, 이 사용자의 이 종류 하루 상한을 **한 문장으로** 확인하고 기록한다(동시에 요청이 몰려도 넘지 않는다).
 * 하루는 UTC 날짜다. 오래된 기록은 이때 지운다.
 */
export async function reserveSend(
  db: Db,
  options: { key: string; kind: SendKind; perUserPerDay: number; now: Date },
): Promise<Reservation> {
  const day = options.now.toISOString().slice(0, 10);
  const oldest = new Date(
    options.now.getTime() - RETENTION_DAYS * 24 * 60 * 60 * 1000,
  )
    .toISOString()
    .slice(0, 10);
  await db
    .prepare("DELETE FROM mail_sends WHERE sent_on < ?")
    .bind(oldest)
    .run();
  const token = crypto.randomUUID();
  const reserved = await db
    .prepare(
      `INSERT INTO mail_sends (user_key, kind, sent_on, token, created_at)
       SELECT ?1, ?7, ?2, ?3, ?4
       WHERE (SELECT COUNT(*) FROM mail_sends WHERE sent_on = ?2) < ?5
         AND (SELECT COUNT(*) FROM mail_sends WHERE sent_on = ?2 AND user_key = ?1 AND kind = ?7) < ?6`,
    )
    .bind(
      options.key,
      day,
      token,
      options.now.toISOString(),
      LIMITS.perDayTotal,
      options.perUserPerDay,
      options.kind,
    )
    .run();
  if (reserved.meta.changes > 0) return { ok: true, token };
  const mine = await db
    .prepare(
      "SELECT COUNT(*) AS n FROM mail_sends WHERE sent_on = ? AND user_key = ? AND kind = ?",
    )
    .bind(day, options.key, options.kind)
    .first<{ n: number }>();
  return { ok: false, personal: (mine?.n ?? 0) >= options.perUserPerDay };
}

/** 서비스가 **접수하지 않았음이 확실한** 실패에서 자리를 돌려준다(접수됐을 수 있는 실패는 돌려주지 않는다 — testMail.ts의 설명). */
export async function releaseSend(db: Db, token: string): Promise<void> {
  await db.prepare("DELETE FROM mail_sends WHERE token = ?").bind(token).run();
}

/** 성공한 발송의 접수 번호를 적는다. */
export async function recordSent(
  db: Db,
  token: string,
  providerId: string,
): Promise<void> {
  await db
    .prepare("UPDATE mail_sends SET provider_id = ? WHERE token = ?")
    .bind(providerId, token)
    .run();
}
