import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { fetchUsage } from "../../src/api/usage.ts";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

function respondWith(body: unknown): void {
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(body), { status: 200 })) as typeof fetch;
}

const START = new Date("2026-11-03T00:00:00Z");
const END = new Date("2026-11-04T00:00:00Z");

test("요약이 있는 응답은 그대로 돌려준다", async () => {
  const payload = {
    start: "s",
    end: "e",
    by_process: [],
    summary: { active_seconds: 60, idle_seconds: 0, top: null },
  };
  respondWith(payload);

  assert.deepEqual(await fetchUsage(START, END), payload);
});

test("요약이 없는 옛 hub의 응답은 알아보기 쉬운 오류가 된다", async () => {
  respondWith({ start: "s", end: "e", by_process: [] });

  await assert.rejects(
    fetchUsage(START, END),
    /hub가 이 앱보다 오래된 버전.*다시 실행/,
  );
});
