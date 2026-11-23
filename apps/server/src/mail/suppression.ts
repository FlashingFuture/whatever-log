import type { Db } from "../db.ts";
import { sha256Hex } from "./quota.ts";

export type SuppressionReason = "bounced" | "complained";

/** 주소의 해시: sha256("address:" + 소문자 주소). 원문 주소는 남기지 않는다. */
export function addressHash(email: string): Promise<string> {
  return sha256Hex(`address:${email.trim().toLowerCase()}`);
}

/** 이 주소로는 보내지 않는가(반송·스팸 신고가 온 주소). */
export async function isSuppressed(db: Db, email: string): Promise<boolean> {
  const row = await db
    .prepare(
      "SELECT 1 AS present FROM mail_suppressions WHERE address_hash = ?",
    )
    .bind(await addressHash(email))
    .first();
  return row !== null;
}

/**
 * 이 주소를 보내지 않을 목록에 넣고, 이 주소를 쓰는 사용자의 구독을 끝낸다(`suppressed`). 이미 있으면 처음 사유를 그대로 둔다(여러 번 와도 같다).
 * 계정을 지웠다 다시 만들어도 같은 주소면 다시 보내지 않는다 — 새 도메인의 평판을 지킨다.
 */
export async function suppress(
  db: Db,
  email: string,
  reason: SuppressionReason,
  now: Date,
): Promise<void> {
  const stamp = now.toISOString();
  await db.batch([
    db
      .prepare(
        "INSERT INTO mail_suppressions (address_hash, reason, created_at) VALUES (?, ?, ?) ON CONFLICT(address_hash) DO NOTHING",
      )
      .bind(await addressHash(email), reason, stamp),
    db
      .prepare(
        "UPDATE mail_subscriptions SET status = 'ended', ended_reason = 'suppressed', updated_at = ? " +
          "WHERE status != 'ended' AND user_id IN (SELECT id FROM users WHERE lower(email) = ?)",
      )
      .bind(stamp, email.trim().toLowerCase()),
  ]);
}
