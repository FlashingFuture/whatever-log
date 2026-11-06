import assert from "node:assert/strict";
import { test } from "node:test";

import { generateToken, hashToken } from "../src/auth/sessionToken.ts";

test("토큰은 URL에 안전한 43자(32바이트)이고 매번 다르다", () => {
  const tokens = new Set(Array.from({ length: 50 }, () => generateToken()));

  assert.equal(tokens.size, 50);
  for (const token of tokens) {
    assert.match(token, /^[A-Za-z0-9_-]{43}$/);
  }
});

test("해시는 SHA-256 16진수이고 같은 토큰에는 같다", async () => {
  // SHA-256("abc") 표준 값
  assert.equal(
    await hashToken("abc"),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
  assert.equal(await hashToken("abc"), await hashToken("abc"));
  assert.notEqual(await hashToken("abc"), await hashToken("abd"));
});
