import type { Db } from "../db.ts";
import { MAX_TOKENS_PER_USER } from "./sessionToken.ts";

/**
 * Google 로그인한 사용자를 만들거나(처음이면) 이메일을 갱신하고(바뀌었을 수 있다), 새 토큰의 해시를 저장한다.
 * 만료된 토큰과 한도(MAX_TOKENS_PER_USER)를 넘는 오래된 토큰은 같은 트랜잭션에서 지운다 — 중간에 실패해도
 * "사용자만 생기고 토큰은 없는" 상태가 남지 않는다.
 */
export async function loginGoogleUser(
  db: Db,
  input: {
    sub: string;
    email: string;
    tokenHash: string;
    now: Date;
    expiresAt: Date;
  },
): Promise<void> {
  const now = input.now.toISOString();
  await db.batch([
    db
      .prepare(
        "INSERT INTO users (google_sub, email, created_at, updated_at) VALUES (?, ?, ?, ?) " +
          "ON CONFLICT(google_sub) DO UPDATE SET email = excluded.email, updated_at = excluded.updated_at",
      )
      .bind(input.sub, input.email, now, now),
    db
      .prepare(
        "INSERT INTO tokens (token_hash, user_id, created_at, expires_at) " +
          "SELECT ?, id, ?, ? FROM users WHERE google_sub = ?",
      )
      .bind(input.tokenHash, now, input.expiresAt.toISOString(), input.sub),
    db
      .prepare(
        "DELETE FROM tokens WHERE user_id = (SELECT id FROM users WHERE google_sub = ?) " +
          "AND (expires_at <= ? OR token_hash NOT IN (" +
          "SELECT token_hash FROM tokens WHERE user_id = (SELECT id FROM users WHERE google_sub = ?) " +
          "ORDER BY created_at DESC, rowid DESC LIMIT ?))",
      )
      .bind(input.sub, now, input.sub, MAX_TOKENS_PER_USER),
  ]);
}
