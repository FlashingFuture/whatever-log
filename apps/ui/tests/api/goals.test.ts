import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError } from "../../src/api/client.ts";
import {
  createGoal,
  deleteGoal,
  fetchGoalProgress,
  fetchGoals,
  fetchTrackedProcesses,
  fetchTrackedSites,
  updateGoal,
} from "../../src/api/goals.ts";

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

const INPUT = {
  name: "공부",
  daily_target_minutes: 120,
  weekdays: [0, 1],
  processes: ["Code.exe"],
  sites: [{ browser: "chrome.exe", domain: "youtube.com" }],
};

test("목록과 추적된 프로세스는 GET으로 받는다", async () => {
  const goal = { id: 1, ...INPUT, created_at: "t", updated_at: "t" };
  let calls = stubFetch(() => json({ goals: [goal] }));
  assert.deepEqual(await fetchGoals(), [goal]);
  assert.equal(calls[0].method, "GET");
  assert.ok(calls[0].url.endsWith("/api/goals"));

  calls = stubFetch(() => json({ processes: ["a.exe", "b.exe"] }));
  assert.deepEqual(await fetchTrackedProcesses(), ["a.exe", "b.exe"]);
  assert.ok(calls[0].url.endsWith("/api/processes"));
});

test("만들기는 POST, 본문은 JSON이고 Content-Type을 단다(hub는 JSON 요청만 받는다)", async () => {
  const calls = stubFetch(() => json({ id: 1, ...INPUT }, 201));

  await createGoal(INPUT);

  assert.equal(calls[0].method, "POST");
  assert.ok(calls[0].url.endsWith("/api/goals"));
  assert.equal(calls[0].headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].body ?? ""), INPUT);
});

test("수정은 PUT /api/goals/<id>, 모든 칸을 그대로 보낸다(사용자가 넣은 값을 고치지 않는다)", async () => {
  const calls = stubFetch(() => json({ id: 7, ...INPUT }));
  const typedAsString = { ...INPUT, daily_target_minutes: "120" };

  await updateGoal(7, typedAsString);

  assert.equal(calls[0].method, "PUT");
  assert.ok(calls[0].url.endsWith("/api/goals/7"));
  assert.equal(JSON.parse(calls[0].body ?? "").daily_target_minutes, "120");
});

test("삭제는 DELETE이고 본문이 없다(204 응답을 받아도 오류가 아니다)", async () => {
  const calls = stubFetch(() => new Response(null, { status: 204 }));

  await deleteGoal(3);

  assert.equal(calls[0].method, "DELETE");
  assert.ok(calls[0].url.endsWith("/api/goals/3"));
  assert.equal(calls[0].body, undefined);
  assert.equal(calls[0].headers["Content-Type"], undefined);
});

test("수행 시간은 구간을 쿼리로 보낸다", async () => {
  const start = new Date("2026-11-03T00:00:00Z");
  const end = new Date("2026-11-04T00:00:00Z");
  const calls = stubFetch(() =>
    json({
      start: "s",
      end: "e",
      goals: [],
      summary: { active_seconds: 0, top: null },
    }),
  );

  await fetchGoalProgress(start, end);

  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/api/goals/progress");
  assert.equal(url.searchParams.get("start"), start.toISOString());
  assert.equal(url.searchParams.get("end"), end.toISOString());
});

test("입력 오류의 칸별 목록이 ApiError.fields에 담긴다", async () => {
  stubFetch(() =>
    json(
      {
        error: {
          code: "invalid_request",
          message: "입력을 확인해 주세요.",
          fields: [
            {
              field: "name",
              code: "length",
              message: "이름은 1~50자여야 합니다.",
            },
            { nope: 1 }, // 모양이 틀린 항목은 버린다
          ],
        },
      },
      400,
    ),
  );

  await assert.rejects(createGoal(INPUT), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 400);
    assert.deepEqual(error.fields, [
      { field: "name", code: "length", message: "이름은 1~50자여야 합니다." },
    ]);
    return true;
  });
});

test("칸 목록이 없는 오류는 fields가 빈 목록이다", async () => {
  stubFetch(() =>
    json(
      { error: { code: "forbidden", message: "허용되지 않은 출처입니다." } },
      403,
    ),
  );

  await assert.rejects(deleteGoal(1), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.deepEqual(error.fields, []);
    assert.equal(error.code, "forbidden");
    return true;
  });
});

test("추적된 사이트는 GET /api/tracked-sites로 받는다", async () => {
  const sites = [{ browser: "chrome.exe", domain: "youtube.com" }];
  const calls = stubFetch(() => json({ sites }));

  assert.deepEqual(await fetchTrackedSites(), sites);
  assert.equal(calls[0].method, "GET");
  assert.ok(calls[0].url.endsWith("/api/tracked-sites"));
});
