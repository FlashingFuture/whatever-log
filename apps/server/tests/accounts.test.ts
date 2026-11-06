import assert from "node:assert/strict";
import { test } from "node:test";

import { loginGoogleUser } from "../src/auth/accounts.ts";
import { MAX_TOKENS_PER_USER } from "../src/auth/sessionToken.ts";
import { createFakeD1 } from "./helpers/fakeD1.ts";

const DAY = 24 * 60 * 60 * 1000;
const T0 = new Date("2026-11-06T03:00:00.000Z");

function login(
  db: ReturnType<typeof createFakeD1>["db"],
  overrides: Partial<{
    sub: string;
    email: string;
    tokenHash: string;
    now: Date;
    expiresAt: Date;
  }> = {},
) {
  const now = overrides.now ?? T0;
  return loginGoogleUser(db as never, {
    sub: "sub-1",
    email: "a@example.com",
    tokenHash: "hash-1",
    now,
    expiresAt: new Date(now.getTime() + 30 * DAY),
    ...overrides,
  });
}

const users = (sqlite: ReturnType<typeof createFakeD1>["sqlite"]) =>
  sqlite.prepare("SELECT * FROM users").all();
const tokens = (sqlite: ReturnType<typeof createFakeD1>["sqlite"]) =>
  sqlite
    .prepare("SELECT token_hash FROM tokens ORDER BY rowid")
    .all()
    .map((row) => row.token_hash);

test("처음 로그인하면 사용자와 토큰 해시가 저장된다", async () => {
  const { db, sqlite } = createFakeD1();

  await login(db);

  assert.deepEqual(
    users(sqlite).map((u) => [u.google_sub, u.email, u.created_at]),
    [["sub-1", "a@example.com", T0.toISOString()]],
  );
  assert.deepEqual(tokens(sqlite), ["hash-1"]);
  const [token] = sqlite.prepare("SELECT * FROM tokens").all();
  assert.equal(
    token?.expires_at,
    new Date(T0.getTime() + 30 * DAY).toISOString(),
  );
});

test("다시 로그인하면 같은 사용자를 쓰고 이메일만 갱신하며 토큰이 하나 더 생긴다", async () => {
  const { db, sqlite } = createFakeD1();
  await login(db);

  const later = new Date(T0.getTime() + DAY);
  await login(db, {
    email: "new@example.com",
    tokenHash: "hash-2",
    now: later,
  });

  const rows = users(sqlite);
  assert.equal(rows.length, 1);
  assert.deepEqual(
    [rows[0]?.email, rows[0]?.created_at, rows[0]?.updated_at],
    ["new@example.com", T0.toISOString(), later.toISOString()],
  );
  assert.deepEqual(tokens(sqlite), ["hash-1", "hash-2"]);
});

test("사용자마다 따로 저장되고 서로의 토큰을 지우지 않는다", async () => {
  const { db, sqlite } = createFakeD1();

  await login(db, { sub: "a", tokenHash: "ha" });
  await login(db, { sub: "b", tokenHash: "hb" });

  assert.equal(users(sqlite).length, 2);
  assert.deepEqual(tokens(sqlite), ["ha", "hb"]);
});

test("토큰은 사용자당 한도까지만 남고 가장 오래된 것부터 지워진다", async () => {
  const { db, sqlite } = createFakeD1();
  const total = MAX_TOKENS_PER_USER + 2;

  for (let i = 1; i <= total; i++) {
    await login(db, {
      tokenHash: `h${i}`,
      now: new Date(T0.getTime() + i * 1000),
    });
  }

  const kept = tokens(sqlite);
  assert.equal(kept.length, MAX_TOKENS_PER_USER);
  assert.deepEqual(
    kept,
    Array.from(
      { length: MAX_TOKENS_PER_USER },
      (_, i) => `h${total - MAX_TOKENS_PER_USER + 1 + i}`,
    ),
  );
});

test("만료된 토큰은 다음 로그인 때 지워진다", async () => {
  const { db, sqlite } = createFakeD1();
  await login(db, {
    tokenHash: "old",
    expiresAt: new Date(T0.getTime() + DAY),
  });

  await login(db, { tokenHash: "new", now: new Date(T0.getTime() + 2 * DAY) });

  assert.deepEqual(tokens(sqlite), ["new"]);
});

test("같은 시각에 연달아 로그인해도 방금 만든 토큰은 남는다", async () => {
  const { db, sqlite } = createFakeD1();

  for (let i = 1; i <= MAX_TOKENS_PER_USER + 1; i++) {
    await login(db, { tokenHash: `h${i}` }); // 모두 같은 now
  }

  const kept = tokens(sqlite);
  assert.equal(kept.length, MAX_TOKENS_PER_USER);
  assert.ok(kept.includes(`h${MAX_TOKENS_PER_USER + 1}`));
});

test("사용자를 지우면 토큰도 함께 지워진다(계정 삭제)", async () => {
  const { db, sqlite } = createFakeD1();
  await login(db);

  sqlite.prepare("DELETE FROM users WHERE google_sub = ?").run("sub-1");

  assert.deepEqual(tokens(sqlite), []);
});

test("중간에 실패하면 모두 되돌린다(사용자만 생기지 않는다)", async () => {
  const { db, sqlite } = createFakeD1();
  await login(db, { tokenHash: "dup" });

  await assert.rejects(() => login(db, { sub: "sub-2", tokenHash: "dup" })); // token_hash는 유일해야 한다

  assert.equal(users(sqlite).length, 1);
});
