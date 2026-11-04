import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const realFetch = globalThis.fetch;
let counter = 0;

afterEach(() => {
  globalThis.fetch = realFetch;
});

/** 모듈 안의 캐시가 테스트끼리 섞이지 않게, 매번 새 모듈 인스턴스를 불러온다. */
async function freshModule() {
  counter += 1;
  return import(`../../src/api/browsers.ts?fresh=${counter}`) as Promise<
    typeof import("../../src/api/browsers.ts")
  >;
}

function stubFetch(handler: () => Response | Promise<Response>): {
  calls: number;
} {
  const state = { calls: 0 };
  globalThis.fetch = (async () => {
    state.calls += 1;
    return handler();
  }) as typeof fetch;
  return state;
}

const ok = () =>
  new Response(JSON.stringify({ browsers: ["chrome.exe", "msedge.exe"] }), {
    status: 200,
  });

test("서버가 알려 준 브라우저인지 판정하고, 목록은 한 번만 받는다", async () => {
  const { isSiteTrackingBrowser } = await freshModule();
  const state = stubFetch(ok);

  assert.equal(await isSiteTrackingBrowser("chrome.exe"), true);
  assert.equal(await isSiteTrackingBrowser("msedge.exe"), true);
  assert.equal(await isSiteTrackingBrowser("Code.exe"), false);

  assert.equal(state.calls, 1);
});

test("동시에 여러 번 물어도 요청은 한 번이다", async () => {
  const { isSiteTrackingBrowser } = await freshModule();
  const state = stubFetch(ok);

  const answers = await Promise.all(
    ["chrome.exe", "Code.exe", "msedge.exe"].map(isSiteTrackingBrowser),
  );

  assert.deepEqual(answers, [true, false, true]);
  assert.equal(state.calls, 1);
});

test("목록을 못 받으면 false이고, 실패는 기억하지 않아 다음에 다시 받는다", async () => {
  const { isSiteTrackingBrowser } = await freshModule();
  let failing = true;
  const state = stubFetch(() =>
    failing ? new Response("down", { status: 503 }) : ok(),
  );

  assert.equal(await isSiteTrackingBrowser("chrome.exe"), false);
  failing = false;
  assert.equal(await isSiteTrackingBrowser("chrome.exe"), true);

  assert.equal(state.calls, 2);
});
