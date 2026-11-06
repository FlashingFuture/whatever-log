import assert from "node:assert/strict";
import { test } from "node:test";

import { IdTokenError, verifyIdToken } from "../src/auth/idToken.ts";
import { CLIENT_ID, createIssuer, NOW } from "./helpers/googleFixtures.ts";

async function verify(
  token: string,
  issuer: Awaited<ReturnType<typeof createIssuer>>,
) {
  return verifyIdToken(token, {
    clientId: CLIENT_ID,
    now: NOW,
    keys: issuer.keys,
  });
}

async function rejection(promise: Promise<unknown>): Promise<IdTokenError> {
  try {
    await promise;
  } catch (error) {
    assert.ok(error instanceof IdTokenError, String(error));
    return error;
  }
  assert.fail("거부돼야 한다");
}

test("올바른 토큰에서 sub와 이메일을 꺼낸다", async () => {
  const issuer = await createIssuer();

  assert.deepEqual(await verify(await issuer.idToken(), issuer), {
    sub: "google-user-1",
    email: "person@example.com",
  });
});

test("발급자는 두 가지 표기를 모두 받는다", async () => {
  const issuer = await createIssuer();

  for (const iss of ["https://accounts.google.com", "accounts.google.com"]) {
    assert.equal(
      (await verify(await issuer.idToken({ iss }), issuer)).sub,
      "google-user-1",
    );
  }
});

test("다른 키로 서명했거나 내용을 바꾼 토큰은 거부한다", async () => {
  const issuer = await createIssuer();
  const attacker = await createIssuer(); // 같은 kid, 다른 키
  const forged = await attacker.idToken();
  assert.equal((await rejection(verify(forged, issuer))).kind, "invalid_token");

  const [header, , signature] = (await issuer.idToken()).split(".");
  const other = (await issuer.idToken({ email: "other@example.com" })).split(
    ".",
  )[1];
  assert.equal(
    (await rejection(verify(`${header}.${other}.${signature}`, issuer))).kind,
    "invalid_token",
  );
});

test("RS256이 아닌 알고리즘과 kid 없는 헤더는 거부한다", async () => {
  const issuer = await createIssuer();
  const claims = {
    iss: "accounts.google.com",
    aud: CLIENT_ID,
    sub: "x",
    email: "a@b.c",
    email_verified: true,
    exp: 9999999999,
  };

  for (const header of [
    { alg: "none", kid: "key-1" },
    { alg: "HS256", kid: "key-1" },
    { alg: "RS256" },
  ]) {
    assert.equal(
      (await rejection(verify(await issuer.sign(claims, header), issuer))).kind,
      "invalid_token",
    );
  }
});

test("모르는 kid는 거부한다", async () => {
  const issuer = await createIssuer("key-1");
  const other = await createIssuer("key-2");

  assert.equal(
    (await rejection(verify(await other.idToken(), issuer))).kind,
    "invalid_token",
  );
});

test("형식이 깨진 토큰은 거부한다", async () => {
  const issuer = await createIssuer();

  for (const token of [
    "",
    "a.b",
    "a.b.c.d",
    "a..c",
    "!!!.???.***",
    "e30.e30.e30",
  ]) {
    assert.equal(
      (await rejection(verify(token, issuer))).kind,
      "invalid_token",
      token,
    );
  }
});

test("발급자, 대상, 만료를 검사한다", async () => {
  const issuer = await createIssuer();
  const nowSeconds = Math.floor(NOW.getTime() / 1000);

  const cases: [string, Record<string, unknown>][] = [
    ["발급자", { iss: "https://evil.example" }],
    ["대상", { aud: "someone-else.apps.googleusercontent.com" }],
    ["대상 배열", { aud: [CLIENT_ID] }],
    ["만료", { exp: nowSeconds - 1 }],
    ["만료 지금", { exp: nowSeconds }],
    ["만료 없음", { exp: undefined }],
    ["만료 문자열", { exp: String(nowSeconds + 100) }],
  ];
  for (const [name, overrides] of cases) {
    assert.equal(
      (await rejection(verify(await issuer.idToken(overrides), issuer))).kind,
      "invalid_token",
      name,
    );
  }
});

test("sub와 이메일 형식을 검사한다", async () => {
  const issuer = await createIssuer();

  const cases: Record<string, unknown>[] = [
    { sub: "" },
    { sub: 123 },
    { sub: "x".repeat(256) },
    { email: "" },
    { email: "no-at-sign" },
    { email: "a b@example.com" },
    { email: "a@example.com\n" },
    { email: 5 },
    { email: `${"a".repeat(251)}@b.c` },
  ];
  for (const overrides of cases) {
    assert.equal(
      (await rejection(verify(await issuer.idToken(overrides), issuer))).kind,
      "invalid_token",
      JSON.stringify(overrides),
    );
  }
});

test("이메일이 검증되지 않은 계정은 따로 알린다", async () => {
  const issuer = await createIssuer();

  for (const email_verified of [false, "true", undefined, 1]) {
    assert.equal(
      (
        await rejection(
          verify(await issuer.idToken({ email_verified }), issuer),
        )
      ).kind,
      "email_not_verified",
    );
  }
});
