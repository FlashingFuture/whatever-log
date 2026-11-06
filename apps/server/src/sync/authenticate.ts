import { hashToken } from "../auth/sessionToken.ts";
import type { Db } from "../db.ts";
import { errorResponse } from "../http.ts";

// generateToken이 만드는 모양(32바이트의 base64url = 43자). 모양이 다르면 DB까지 가지 않는다.
const TOKEN_FORMAT = /^[A-Za-z0-9_-]{43}$/;

export interface Caller {
  userId: number;
  tokenHash: string;
}

/**
 * `Authorization: Bearer <토큰>`을 확인해 호출한 사용자를 돌려준다. 없거나 잘못됐거나 만료됐으면 401 응답을
 * 돌려준다. 어느 경우인지(없는 토큰/만료)는 구분해서 알려 주지 않는다.
 */
export async function authenticate(
  request: Request,
  db: Db,
  now: Date,
): Promise<Caller | Response> {
  const rejected = () =>
    errorResponse(
      401,
      "invalid_token",
      "로그인이 필요합니다. 다시 로그인해 주세요.",
      { "WWW-Authenticate": "Bearer" },
    );
  const match = /^Bearer (\S+)$/.exec(
    request.headers.get("Authorization") ?? "",
  );
  if (!match || !TOKEN_FORMAT.test(match[1])) {
    return rejected();
  }
  const tokenHash = await hashToken(match[1]);
  const row = await db
    .prepare(
      "SELECT user_id FROM tokens WHERE token_hash = ? AND expires_at > ?",
    )
    .bind(tokenHash, now.toISOString())
    .first<{ user_id: number }>();
  return row ? { userId: row.user_id, tokenHash } : rejected();
}
