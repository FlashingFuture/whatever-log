import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/api/client.ts";
import { applySync, fetchSyncPlan } from "../../src/api/sync.ts";

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

test("계획은 GET /api/sync/plan이다", async () => {
  const plan = { email: "a@example.com", enabled: false, items: [] };
  const calls = stubFetch(() => json(plan));

  assert.deepEqual(await fetchSyncPlan(), plan);

  assert.equal(calls[0].method, "GET");
  assert.ok(calls[0].url.endsWith("/api/sync/plan"));
});

test("적용은 체크한 key 목록만 JSON으로 보낸다", async () => {
  const calls = stubFetch(() =>
    json({ uploaded: 1, merged: 0, downloaded: 0, kept_local: 0, errors: [] }),
  );

  const result = await applySync(["local:1", "remote:r-1"]);

  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/api/sync/apply"));
  assert.equal(calls[0].headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].body ?? ""), {
    accepted: ["local:1", "remote:r-1"],
  });
  assert.equal(result.uploaded, 1);
});

test("서버에 닿지 못한 사유는 사용자용 문장 그대로 ApiError로 올라온다", async () => {
  stubFetch(() =>
    json(
      {
        error: { code: "unavailable", message: "서버에 연결하지 못했습니다." },
      },
      503,
    ),
  );

  await assert.rejects(
    () => fetchSyncPlan(),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 503 &&
      error.message === "서버에 연결하지 못했습니다.",
  );
});
