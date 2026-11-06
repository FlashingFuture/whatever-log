import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { type Env } from "../src/index.ts";
import { createFakeD1 } from "./helpers/fakeD1.ts";
import { CLIENT_ID, VALID_BODY } from "./helpers/googleFixtures.ts";

function env(): Env {
  return {
    GOOGLE_CLIENT_ID: CLIENT_ID,
    GOOGLE_CLIENT_SECRET: "secret",
    DB: createFakeD1().db as never,
  };
}

const call = (request: Request) => worker.fetch(request, env(), {} as never);

test("/health는 200이다", async () => {
  const response = await call(new Request("https://server.example/health"));

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
});

test("/auth/google은 POST만 받는다", async () => {
  for (const method of ["GET", "PUT", "DELETE"]) {
    const response = await call(
      new Request("https://server.example/auth/google", { method }),
    );

    assert.equal(response.status, 405, method);
    assert.equal(response.headers.get("Allow"), "POST");
  }
});

test("없는 주소는 404 JSON 오류이다", async () => {
  const response = await call(new Request("https://server.example/nope"));

  assert.equal(response.status, 404);
  assert.equal(
    ((await response.json()) as { error: { code: string } }).error.code,
    "not_found",
  );
});

test("POST /auth/google의 본문 검사는 Worker를 통해서도 동작한다", async () => {
  const response = await call(
    new Request("https://server.example/auth/google", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...VALID_BODY,
        redirect_uri: "https://evil.example/cb",
      }),
    }),
  );

  assert.equal(response.status, 400);
});

test("예상하지 못한 오류는 500이고 내용을 응답에 담지 않는다", async () => {
  const broken = { ...env(), DB: undefined as never };
  const request = new Request("https://server.example/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(VALID_BODY),
  });

  // 코드 교환 단계에서 실제 Google에 가지 않도록 fetch를 막아 둔다.
  const original = globalThis.fetch;
  globalThis.fetch = async () => {
    throw new Error("blocked in test");
  };
  try {
    const response = await worker.fetch(request, broken, {} as never);
    assert.equal(response.status, 502); // 코드 교환 실패는 upstream 오류로 처리된다
  } finally {
    globalThis.fetch = original;
  }
});
