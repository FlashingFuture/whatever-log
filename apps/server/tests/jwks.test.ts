import assert from "node:assert/strict";
import { test } from "node:test";
import { createGoogleKeyProvider, GOOGLE_JWKS_URL } from "../src/auth/jwks.ts";
import { createIssuer, jsonResponse } from "./helpers/googleFixtures.ts";

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;

function setup(keysByCall: unknown[][]) {
  const clock = { now: 1_000_000 };
  const calls: string[] = [];
  const fetchFn = async (url: string) => {
    calls.push(url);
    const keys = keysByCall[Math.min(calls.length - 1, keysByCall.length - 1)];
    return jsonResponse({ keys });
  };
  return {
    clock,
    calls,
    provider: createGoogleKeyProvider(fetchFn, () => clock.now),
  };
}

test("처음 요청에 공개키를 받아 오고, 같은 키는 1시간 동안 다시 받지 않는다", async () => {
  const { publicJwk } = await createIssuer("k1");
  const { provider, calls, clock } = setup([[publicJwk]]);

  assert.equal((await provider.get("k1"))?.kid, "k1");
  clock.now += 59 * MINUTE;
  assert.equal((await provider.get("k1"))?.kid, "k1");

  assert.deepEqual(calls, [GOOGLE_JWKS_URL]);
});

test("1시간이 지나면 다시 받는다", async () => {
  const { publicJwk } = await createIssuer("k1");
  const { provider, calls, clock } = setup([[publicJwk]]);

  await provider.get("k1");
  clock.now += HOUR;
  await provider.get("k1");

  assert.equal(calls.length, 2);
});

test("모르는 kid는 키가 교체됐을 수 있어 다시 받아 보되, 1분에 한 번만 받는다", async () => {
  const first = await createIssuer("k1");
  const second = await createIssuer("k2");
  const { provider, calls, clock } = setup([
    [first.publicJwk],
    [first.publicJwk, second.publicJwk],
  ]);

  await provider.get("k1");
  assert.equal(await provider.get("k2"), undefined); // 방금 받았으니 아직 다시 받지 않는다
  assert.equal(calls.length, 1);

  clock.now += MINUTE;
  assert.equal((await provider.get("k2"))?.kid, "k2"); // 1분이 지나 다시 받아 새 키를 찾는다
  assert.equal(calls.length, 2);

  for (let i = 0; i < 5; i++) {
    assert.equal(await provider.get("nope"), undefined);
  }
  assert.equal(calls.length, 2); // 가짜 kid를 반복해도 Google에 가지 않는다
});

test("RSA가 아니거나 kid가 없는 항목은 무시한다", async () => {
  const { publicJwk } = await createIssuer("k1");
  const { provider } = setup([
    [
      { kty: "EC", kid: "ec", crv: "P-256" },
      { kty: "RSA", n: "x", e: "AQAB" },
      publicJwk,
    ],
  ]);

  assert.equal(await provider.get("ec"), undefined);
  assert.equal((await provider.get("k1"))?.kid, "k1");
});

test("키 요청이 실패하면 오류를 올린다", async () => {
  const provider = createGoogleKeyProvider(
    async () => new Response("down", { status: 503 }),
    () => 0,
  );

  await assert.rejects(() => provider.get("k1"), /503/);
});

test("키를 한 번도 받지 못한 채 실패했으면 1분을 기다리지 않고 바로 다시 시도한다", async () => {
  let calls = 0;
  const provider = createGoogleKeyProvider(
    async () => {
      calls += 1;
      return calls === 1
        ? new Response("down", { status: 503 })
        : jsonResponse({ keys: [{ kty: "RSA", kid: "k1" }] });
    },
    () => 5 * HOUR,
  );

  await assert.rejects(() => provider.get("k1"), /503/);
  assert.equal((await provider.get("k1"))?.kid, "k1");
  assert.equal(calls, 2);
});

test("키가 있을 때의 갱신 실패는 1분 간격 제한을 그대로 지킨다", async () => {
  const clock = { now: 0 };
  let calls = 0;
  const provider = createGoogleKeyProvider(
    async () => {
      calls += 1;
      return calls === 1
        ? jsonResponse({ keys: [{ kty: "RSA", kid: "k1" }] })
        : new Response("down", { status: 503 });
    },
    () => clock.now,
  );
  await provider.get("k1");

  clock.now = 2 * MINUTE;
  await assert.rejects(() => provider.get("unknown"), /503/);
  await provider.get("unknown"); // 방금 실패했으니 Google에 다시 가지 않는다
  assert.equal(calls, 2);
});
