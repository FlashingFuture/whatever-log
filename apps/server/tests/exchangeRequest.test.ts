import assert from "node:assert/strict";
import { test } from "node:test";

import { parseExchangeRequest } from "../src/auth/exchangeRequest.ts";
import { VALID_BODY } from "./helpers/googleFixtures.ts";

test("올바른 본문은 그대로 받는다", () => {
  assert.deepEqual(parseExchangeRequest(VALID_BODY), {
    ok: true,
    value: {
      code: VALID_BODY.code,
      codeVerifier: VALID_BODY.code_verifier,
      redirectUri: VALID_BODY.redirect_uri,
    },
  });
});

test("JSON 객체가 아니면 거부한다", () => {
  for (const body of [null, [], "text", 1, undefined]) {
    assert.equal(parseExchangeRequest(body).ok, false, String(body));
  }
});

test("모르는 칸이 있으면 거부한다", () => {
  const result = parseExchangeRequest({ ...VALID_BODY, extra: 1 });

  assert.equal(result.ok, false);
  assert.match(!result.ok ? result.message : "", /extra/);
});

test("빠진 칸과 잘못된 형식을 거부한다", () => {
  for (const key of Object.keys(VALID_BODY)) {
    const { [key as keyof typeof VALID_BODY]: _removed, ...rest } = VALID_BODY;
    assert.equal(parseExchangeRequest(rest).ok, false, `${key} 없음`);
    assert.equal(
      parseExchangeRequest({ ...VALID_BODY, [key]: 1 }).ok,
      false,
      `${key} 숫자`,
    );
    assert.equal(
      parseExchangeRequest({ ...VALID_BODY, [key]: "" }).ok,
      false,
      `${key} 빈 값`,
    );
  }
});

test("code는 공백이 없고 너무 길지 않아야 한다", () => {
  assert.equal(parseExchangeRequest({ ...VALID_BODY, code: "a b" }).ok, false);
  assert.equal(parseExchangeRequest({ ...VALID_BODY, code: "a\n" }).ok, false);
  assert.equal(
    parseExchangeRequest({ ...VALID_BODY, code: "a".repeat(2049) }).ok,
    false,
  );
  assert.equal(
    parseExchangeRequest({ ...VALID_BODY, code: "a".repeat(2048) }).ok,
    true,
  );
});

test("code_verifier는 43~128자의 허용된 글자만 받는다", () => {
  for (const bad of [
    "a".repeat(42),
    "a".repeat(129),
    `${"a".repeat(42)}+`,
    `${"a".repeat(42)} `,
  ]) {
    assert.equal(
      parseExchangeRequest({ ...VALID_BODY, code_verifier: bad }).ok,
      false,
      bad,
    );
  }
  assert.equal(
    parseExchangeRequest({
      ...VALID_BODY,
      code_verifier: `${"a".repeat(40)}-._~`,
    }).ok,
    true,
  );
  assert.equal(
    parseExchangeRequest({ ...VALID_BODY, code_verifier: "a".repeat(128) }).ok,
    true,
  );
});

test("redirect_uri는 로컬 루프백 http 주소만 받는다", () => {
  for (const ok of [
    "http://127.0.0.1:53412",
    "http://127.0.0.1:53412/callback",
    "http://localhost:8080/oauth/callback",
    "http://[::1]:9000/cb",
    "http://127.0.0.1:1/cb", // 포트 경계
    "http://127.0.0.1:65535/cb",
  ]) {
    assert.equal(
      parseExchangeRequest({ ...VALID_BODY, redirect_uri: ok }).ok,
      true,
      ok,
    );
  }
  for (const bad of [
    "https://127.0.0.1:53412/callback", // https 아님
    "http://127.0.0.1/callback", // 포트 없음
    "http://evil.example:53412/callback",
    "http://127.0.0.1.evil.example:53412/callback",
    "http://127.0.0.1@evil.example:53412/",
    "http://127.0.0.1:53412/callback?x=1",
    "http://127.0.0.1:53412/callback#frag",
    "http://127.0.0.1:99999999/callback",
    "http://127.0.0.1:65536/callback", // 포트 범위 밖
    "http://127.0.0.1:99999/callback",
    "http://127.0.0.1:0/callback",
    "com.example.app:/oauth",
    "http://0.0.0.0:5000/",
  ]) {
    assert.equal(
      parseExchangeRequest({ ...VALID_BODY, redirect_uri: bad }).ok,
      false,
      bad,
    );
  }
});
