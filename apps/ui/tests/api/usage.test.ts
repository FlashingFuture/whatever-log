import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { fetchUsage } from "../../src/api/usage.ts";

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

/** fetch를 가짜로 바꾸고, 화면이 실제로 보낸 요청 주소를 돌려준다. */
function respondWith(body: unknown): { requested: string[] } {
  const state = { requested: [] as string[] };
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    state.requested.push(String(input));
    return new Response(JSON.stringify(body), { status: 200 });
  }) as typeof fetch;
  return state;
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

test("구간의 시작과 끝을 /api/usage의 쿼리로 보낸다", async () => {
  // 화면은 받은 구간을 요청한 구간과 다시 비교하지 않는다 — 요청이 틀리면 잘못된 기간이 그대로 보인다.
  const state = respondWith({
    start: "s",
    end: "e",
    by_process: [],
    summary: { active_seconds: 0, idle_seconds: 0, top: null },
  });

  await fetchUsage(START, END);

  assert.equal(state.requested.length, 1);
  const url = new URL(state.requested[0]);
  assert.equal(url.pathname, "/api/usage");
  assert.equal(url.searchParams.get("start"), START.toISOString());
  assert.equal(url.searchParams.get("end"), END.toISOString());
});

test("요약이 없는 옛 hub의 응답은 알아보기 쉬운 오류가 된다", async () => {
  respondWith({ start: "s", end: "e", by_process: [] });

  await assert.rejects(
    fetchUsage(START, END),
    /hub가 이 앱보다 오래된 버전.*다시 실행/,
  );
});
