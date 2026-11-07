import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/api/client.ts";
import {
  applySync,
  deleteAccount,
  deleteDevice,
  fetchDevices,
  fetchSyncPlan,
  fetchSyncStatus,
} from "../../src/api/sync.ts";

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

  const result = await applySync(["local:1", "remote:r-1"], "a@example.com");

  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/api/sync/apply"));
  assert.equal(calls[0].headers["Content-Type"], "application/json");
  // email은 확인 창을 연 계정이다 — 그 사이 계정이 바뀌면 hub가 적용하지 않는다.
  assert.deepEqual(JSON.parse(calls[0].body ?? ""), {
    accepted: ["local:1", "remote:r-1"],
    email: "a@example.com",
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

test("상태는 GET /api/sync/status이고 서버를 부르지 않는 로컬 읽기다", async () => {
  const status = {
    enabled: true,
    state: "ok",
    result: "ok",
    last_attempt_at: "t",
    last_success_at: "t",
    problems: 0,
  };
  const calls = stubFetch(() => json(status));

  assert.deepEqual(await fetchSyncStatus(), status);

  assert.equal(calls[0].method, "GET");
  assert.ok(calls[0].url.endsWith("/api/sync/status"));
});

test("기기 목록은 GET이고 목록만 돌려준다", async () => {
  const devices = [
    { device_id: "d-1", last_sent_at: "t", rows: 3, is_this_device: true },
  ];
  const calls = stubFetch(() => json({ devices }));

  assert.deepEqual(await fetchDevices(), devices);
  assert.ok(calls[0].url.endsWith("/api/devices"));
});

test("기기 삭제는 본문 없는 DELETE이고, 이 기기를 지우려 하면 사유가 ApiError로 온다", async () => {
  let calls = stubFetch(() => new Response(null, { status: 204 }));
  await deleteDevice("d-1");
  assert.equal(calls[0].method, "DELETE");
  assert.ok(calls[0].url.endsWith("/api/devices/d-1"));
  assert.equal(calls[0].body, undefined);
  assert.equal(calls[0].headers["Content-Type"], undefined);

  calls = stubFetch(() =>
    json(
      {
        error: {
          code: "unavailable",
          message: "이 기기의 기록은 지울 수 없어요.",
        },
      },
      503,
    ),
  );
  await assert.rejects(
    () => deleteDevice("mine"),
    (error: unknown) =>
      error instanceof ApiError && error.message.includes("이 기기"),
  );
});

test("계정 삭제는 확인한 이메일 하나만 POST로 보낸다", async () => {
  const calls = stubFetch(() =>
    json({
      available: true,
      signed_in: false,
      email: null,
      login: { state: "idle", message: null },
      providers: [],
      sync_enabled: false,
      deleted_on_server: true,
      signed_out: true,
      connections_cleared: true,
    }),
  );

  const result = await deleteAccount("a@example.com");

  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/api/account/delete"));
  assert.deepEqual(JSON.parse(calls[0].body ?? ""), { email: "a@example.com" });
  assert.equal(result.deleted_on_server, true);
});
