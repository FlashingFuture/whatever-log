import assert from "node:assert/strict";
import { test } from "node:test";

import { handleGoogleLogin, type LoginDeps } from "../src/auth/handler.ts";
import { hashToken } from "../src/auth/sessionToken.ts";
import { createFakeD1 } from "./helpers/fakeD1.ts";
import {
  CLIENT_ID,
  createIssuer,
  jsonResponse,
  NOW,
  VALID_BODY,
} from "./helpers/googleFixtures.ts";

const SECRET = "client-secret-value";

async function setup(
  options: {
    exchange?: (url: string, init?: RequestInit) => Promise<Response>;
    idToken?: Record<string, unknown>;
  } = {},
) {
  const issuer = await createIssuer();
  const { db, sqlite } = createFakeD1();
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetch = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return options.exchange
      ? options.exchange(url, init)
      : jsonResponse({ id_token: await issuer.idToken(options.idToken) });
  };
  const deps: LoginDeps = {
    clientId: CLIENT_ID,
    clientSecret: SECRET,
    db: db as never,
    fetch,
    keys: issuer.keys,
    now: () => NOW,
    newToken: () => "fresh-token-value",
  };
  return { deps, sqlite, calls, issuer };
}

function post(
  body: unknown,
  headers: Record<string, string> = { "Content-Type": "application/json" },
): Request {
  return new Request("https://server.example/auth/google", {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function errorOf(
  response: Response,
): Promise<{ status: number; code: string }> {
  const body = (await response.json()) as { error: { code: string } };
  return { status: response.status, code: body.error.code };
}

test("로그인에 성공하면 토큰을 한 번 돌려주고 DB에는 해시만 저장한다", async () => {
  const { deps, sqlite, calls } = await setup();

  const response = await handleGoogleLogin(post(VALID_BODY), deps);

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), {
    token: "fresh-token-value",
    expires_at: "2026-12-06T03:00:00.000Z",
    email: "person@example.com",
  });
  assert.equal(calls.length, 1);
  assert.equal(
    new URLSearchParams(calls[0]?.init?.body as URLSearchParams).get(
      "client_secret",
    ),
    SECRET,
  );

  const stored = JSON.stringify([
    sqlite.prepare("SELECT * FROM users").all(),
    sqlite.prepare("SELECT * FROM tokens").all(),
  ]);
  assert.match(stored, new RegExp(await hashToken("fresh-token-value")));
  assert.doesNotMatch(stored, /fresh-token-value/);
});

test("본문 형식이 틀리면 Google에 가지 않고 거부한다", async () => {
  const { deps, calls } = await setup();
  const cases: [string, Request, number][] = [
    ["Content-Type 없음", post(VALID_BODY, {}), 415],
    ["text/plain", post(VALID_BODY, { "Content-Type": "text/plain" }), 415],
    ["빈 본문", post("", { "Content-Type": "application/json" }), 400],
    ["JSON 아님", post("{oops", { "Content-Type": "application/json" }), 400],
    ["배열", post([], { "Content-Type": "application/json" }), 400],
    ["모르는 칸", post({ ...VALID_BODY, extra: 1 }), 400],
    [
      "루프백이 아닌 주소",
      post({ ...VALID_BODY, redirect_uri: "https://evil.example/cb" }),
      400,
    ],
    ["너무 큰 본문", post({ ...VALID_BODY, code: "a".repeat(5000) }), 413],
  ];

  for (const [name, request, status] of cases) {
    const response = await handleGoogleLogin(request, deps);
    assert.equal(response.status, status, name);
    assert.equal((await errorOf(response)).code, "invalid_request", name);
  }
  assert.equal(calls.length, 0);
});

test("charset이 붙은 JSON Content-Type도 받는다", async () => {
  const { deps } = await setup();

  const response = await handleGoogleLogin(
    post(VALID_BODY, { "Content-Type": "application/json; charset=utf-8" }),
    deps,
  );

  assert.equal(response.status, 200);
});

test("만료되거나 이미 쓴 코드는 400 invalid_grant이다", async () => {
  const { deps, sqlite } = await setup({
    exchange: async () => jsonResponse({ error: "invalid_grant" }, 400),
  });

  const response = await handleGoogleLogin(post(VALID_BODY), deps);

  assert.deepEqual(await errorOf(response), {
    status: 400,
    code: "invalid_grant",
  });
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM users").get()?.n, 0);
});

test("Google 쪽 문제와 설정 문제는 502이고 상세 내용을 응답에 담지 않는다", async () => {
  for (const exchange of [
    async () =>
      jsonResponse({ error: "invalid_client", error_description: SECRET }, 401),
    async () => new Response("down", { status: 503 }),
    async () => {
      throw new Error(`network ${SECRET}`);
    },
  ]) {
    const { deps } = await setup({ exchange });

    const response = await handleGoogleLogin(post(VALID_BODY), deps);
    const text = await response.clone().text();

    assert.deepEqual(await errorOf(response), {
      status: 502,
      code: "upstream_error",
    });
    assert.doesNotMatch(text, new RegExp(SECRET));
  }
});

test("ID 토큰 검증에 실패하면 사용자를 만들지 않는다", async () => {
  for (const idToken of [
    { aud: "other-client" },
    { iss: "https://evil.example" },
    { exp: 1 },
  ]) {
    const { deps, sqlite } = await setup({ idToken });

    const response = await handleGoogleLogin(post(VALID_BODY), deps);

    assert.deepEqual(await errorOf(response), {
      status: 502,
      code: "upstream_error",
    });
    assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM users").get()?.n, 0);
  }
});

test("이메일이 검증되지 않은 계정은 403이다", async () => {
  const { deps, sqlite } = await setup({ idToken: { email_verified: false } });

  const response = await handleGoogleLogin(post(VALID_BODY), deps);

  assert.deepEqual(await errorOf(response), {
    status: 403,
    code: "email_not_verified",
  });
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM users").get()?.n, 0);
});

test("다른 서명 키로 만든 가짜 ID 토큰은 받지 않는다", async () => {
  const attacker = await createIssuer();
  const { deps, sqlite } = await setup({
    exchange: async () => jsonResponse({ id_token: await attacker.idToken() }),
  });

  const response = await handleGoogleLogin(post(VALID_BODY), deps);

  assert.equal(response.status, 502);
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM users").get()?.n, 0);
});
