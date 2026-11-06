import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  cancelLogin,
  fetchAccount,
  logout,
  openExternalLink,
  startLogin,
} from "../../src/api/account.ts";
import { ApiError } from "../../src/api/client.ts";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

interface Call {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | undefined;
}

/** fetch를 가짜로 바꾸고, 화면이 실제로 보낸 요청들을 기록한다. */
function stubFetch(respond: () => Response): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: init?.body as string | undefined,
    });
    return respond();
  }) as typeof fetch;
  return calls;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

const SNAPSHOT = {
  available: true,
  signed_in: false,
  email: null,
  login: { state: "idle", message: null },
  providers: [{ id: "google", label: "Google" }],
};

test("상태 조회는 GET /api/account이다", async () => {
  const calls = stubFetch(() => json(SNAPSHOT));

  assert.deepEqual(await fetchAccount(), SNAPSHOT);

  assert.equal(calls[0].method, "GET");
  assert.ok(calls[0].url.endsWith("/api/account"));
});

test("로그인 시작은 POST로 provider 하나만 JSON으로 보낸다", async () => {
  const calls = stubFetch(() => json(SNAPSHOT, 202));

  await startLogin("google");

  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/api/account/login"));
  assert.equal(calls[0].headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].body ?? ""), { provider: "google" });
});

test("로그인 취소는 본문 없는 DELETE이다", async () => {
  const calls = stubFetch(() => json(SNAPSHOT));

  await cancelLogin();

  assert.equal(calls[0].method, "DELETE");
  assert.ok(calls[0].url.endsWith("/api/account/login"));
  assert.equal(calls[0].body, undefined);
  assert.equal(calls[0].headers["Content-Type"], undefined);
});

test("로그아웃은 본문 없는 POST이고 서버 폐기 여부를 받는다", async () => {
  const calls = stubFetch(() =>
    json({ ...SNAPSHOT, revoked_on_server: false }),
  );

  const result = await logout();

  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/api/account/logout"));
  assert.equal(calls[0].body, undefined);
  assert.equal(result.revoked_on_server, false);
});

test("바깥 링크는 주소가 아니라 이름만 보낸다", async () => {
  const calls = stubFetch(() => new Response(null, { status: 204 }));

  await openExternalLink("privacy");

  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/api/links/open"));
  assert.deepEqual(JSON.parse(calls[0].body ?? ""), { link: "privacy" });
});

test("hub가 준 오류 사유는 ApiError로 올라온다", async () => {
  stubFetch(() =>
    json(
      {
        error: {
          code: "unavailable",
          message: "이 설치에서는 로그인 기능을 쓸 수 없습니다.",
        },
      },
      503,
    ),
  );

  await assert.rejects(
    () => startLogin("google"),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 503 &&
      error.message.includes("로그인 기능"),
  );
});
