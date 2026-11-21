import type { Db } from "../db.ts";

/** 이 토큰 하나를 서버에서 폐기한다(로그아웃). 다른 기기의 토큰은 그대로다. */
export async function revokeToken(db: Db, tokenHash: string): Promise<void> {
  await db
    .prepare("DELETE FROM tokens WHERE token_hash = ?")
    .bind(tokenHash)
    .run();
}

/**
 * 계정을 지운다: 달성도, 목표, 토큰, 사용자를 한 트랜잭션에서 모두 삭제한다. 외래 키의 연쇄 삭제에만 기대지 않고
 * 자식 행부터 명시적으로 지워, 연쇄 삭제 설정이 바뀌어도 데이터가 남지 않게 한다.
 */
export async function deleteAccount(db: Db, userId: number): Promise<void> {
  await db.batch([
    db.prepare("DELETE FROM progress WHERE user_id = ?").bind(userId),
    db.prepare("DELETE FROM goals WHERE user_id = ?").bind(userId),
    // 메일 발송 기록(mail_sends)은 일부러 지우지 않는다 — 계정을 지웠다 다시 만들어 일일 한도를 되돌리지 못하게(해시와 날짜뿐이고 며칠 뒤 자동으로 사라진다).
    db.prepare("DELETE FROM tokens WHERE user_id = ?").bind(userId),
    db.prepare("DELETE FROM users WHERE id = ?").bind(userId),
  ]);
}
