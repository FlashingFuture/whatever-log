import assert from "node:assert/strict";
import { test } from "node:test";

import { GOAL, type Json, setup, uuid } from "./helpers/syncFixtures.ts";

const PERIOD = { start_date: "2026-11-10", end_date: "2026-11-30" };

async function signedIn() {
  const world = setup();
  const token = await world.signIn();
  return { ...world, token };
}

test("기간을 정해 만들면 저장되고 목록에도 나온다", async () => {
  const { call, token } = await signedIn();
  const id = uuid();

  const created = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, ...PERIOD },
  });

  assert.equal(created.status, 201);
  assert.equal(created.json.start_date, "2026-11-10");
  assert.equal(created.json.end_date, "2026-11-30");
  const listed = await call("GET", "/goals", { token });
  assert.deepEqual(listed.json.goals, [created.json]);
});

test("기간 칸이 없는 요청(이전 버전)으로 만들면 기간이 없다", async () => {
  const { call, token } = await signedIn();

  const created = await call("PUT", `/goals/${uuid()}`, { token, body: GOAL });

  assert.equal(created.json.start_date, null);
  assert.equal(created.json.end_date, null);
});

test("기간을 바꾸고 지울 수 있다(null이면 기간 없음)", async () => {
  const { call, token } = await signedIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: { ...GOAL, ...PERIOD } });

  const changed = await call("PUT", `/goals/${id}`, {
    token,
    body: {
      ...GOAL,
      base_revision: 1,
      start_date: "2026-12-01",
      end_date: "2026-12-31",
    },
  });
  assert.equal(changed.status, 200);
  assert.deepEqual(
    [changed.json.start_date, changed.json.end_date, changed.json.revision],
    ["2026-12-01", "2026-12-31", 2],
  );

  const cleared = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, base_revision: 2, start_date: null, end_date: null },
  });
  assert.deepEqual(
    [cleared.json.start_date, cleared.json.end_date],
    [null, null],
  );
});

test("기간 칸 없이 고치면(이전 버전 클라이언트) 다른 기기가 정한 기간을 지우지 않는다", async () => {
  const { call, token } = await signedIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: { ...GOAL, ...PERIOD } });

  const edited = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, name: "공부2", base_revision: 1 },
  });

  assert.equal(edited.status, 200);
  assert.equal(edited.json.name, "공부2");
  assert.deepEqual(
    [edited.json.start_date, edited.json.end_date],
    ["2026-11-10", "2026-11-30"],
  );
});

test("만드는 요청의 재시도는 기간까지 같아야 같은 요청으로 본다", async () => {
  const { call, token } = await signedIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: { ...GOAL, ...PERIOD } });

  const same = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, ...PERIOD },
  });
  assert.equal(same.status, 200);

  const other = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, start_date: "2026-11-11", end_date: "2026-11-30" },
  });
  assert.equal(other.status, 409);
  assert.equal(other.json.current.start_date, "2026-11-10");
});

test("기간이 틀리면 400이고 저장하지 않는다", async () => {
  const { call, token } = await signedIn();
  const cases: [string, Json][] = [
    ["한쪽만", { start_date: "2026-11-10" }],
    ["한쪽만 null", { start_date: null, end_date: "2026-11-30" }],
    ["순서", { start_date: "2026-11-30", end_date: "2026-11-10" }],
    ["없는 날", { start_date: "2026-02-30", end_date: "2026-03-01" }],
    ["모양", { start_date: "2026-1-5", end_date: "2026-01-06" }],
    ["숫자", { start_date: 20261110, end_date: 20261130 }],
    ["범위 밖의 해", { start_date: "1999-12-31", end_date: "2000-01-01" }],
    ["전각 숫자", { start_date: "２０２６-11-10", end_date: "2026-11-30" }],
  ];
  for (const [label, period] of cases) {
    const result = await call("PUT", `/goals/${uuid()}`, {
      token,
      body: { ...GOAL, name: label, ...period },
    });
    assert.equal(result.status, 400, label);
    assert.equal(result.json.error.code, "invalid_request", label);
  }
  assert.deepEqual((await call("GET", "/goals", { token })).json.goals, []);
});

test("하루짜리 기간(시작 = 종료)은 받는다", async () => {
  const { call, token } = await signedIn();
  const result = await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, start_date: "2026-11-10", end_date: "2026-11-10" },
  });
  assert.equal(result.status, 201);
});

test("삭제하면 기간도 남기지 않는다(삭제 표시에는 내용이 없다)", async () => {
  const { call, token, sqlite } = await signedIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: { ...GOAL, ...PERIOD } });

  assert.equal((await call("DELETE", `/goals/${id}`, { token })).status, 204);

  const row = sqlite
    .prepare("SELECT start_date, end_date FROM goals WHERE id = ?")
    .get(id) as Json;
  assert.deepEqual([row.start_date, row.end_date], [null, null]);
});

// --- 보낸 달성 줄 지우기 ---

async function withProgress() {
  const world = await signedIn();
  const goalId = uuid();
  await world.call("PUT", `/goals/${goalId}`, {
    token: world.token,
    body: GOAL,
  });
  const mine = uuid();
  const other = uuid();
  for (const device of [mine, other]) {
    await world.call("PUT", "/progress", {
      token: world.token,
      body: {
        device_id: device,
        entries: ["2026-11-04", "2026-11-05"].map((day) => ({
          goal_id: goalId,
          day,
          minutes: 30,
          target_minutes: 60,
        })),
      },
    });
  }
  return { ...world, goalId, mine, other };
}

const rows = (sqlite: ReturnType<typeof setup>["sqlite"]) =>
  sqlite
    .prepare("SELECT device_id, day FROM progress ORDER BY device_id, day")
    .all()
    .map((row) => `${(row as Json).device_id.slice(-1)}:${(row as Json).day}`);

test("이 기기가 보낸 줄만 지우고 다른 기기의 줄은 남긴다", async () => {
  const { call, token, goalId, mine, sqlite } = await withProgress();

  const removed = await call("POST", "/progress/remove", {
    token,
    body: {
      device_id: mine,
      entries: [{ goal_id: goalId, day: "2026-11-05" }],
    },
  });

  assert.equal(removed.status, 200);
  assert.equal(removed.json.removed, 1);
  const mineTail = mine.slice(-1);
  const left = rows(sqlite);
  assert.equal(left.length, 3);
  assert.ok(!left.includes(`${mineTail}:2026-11-05`));

  // 다시 보내도 같다(없는 줄은 넘어간다)
  const again = await call("POST", "/progress/remove", {
    token,
    body: {
      device_id: mine,
      entries: [{ goal_id: goalId, day: "2026-11-05" }],
    },
  });
  assert.equal(again.json.removed, 0);
});

test("다른 사용자의 줄은 지우지 못한다", async () => {
  const { call, signIn, goalId, mine, sqlite } = await withProgress();
  const stranger = await signIn("sub-2", "b@example.com");

  const result = await call("POST", "/progress/remove", {
    token: stranger,
    body: {
      device_id: mine,
      entries: [{ goal_id: goalId, day: "2026-11-05" }],
    },
  });

  assert.equal(result.json.removed, 0);
  assert.equal(rows(sqlite).length, 4);
});

test("지우기 요청의 모양이 틀리면 400이다", async () => {
  const { call, token, goalId, mine } = await withProgress();
  const cases: [string, unknown][] = [
    ["빈 목록", { device_id: mine, entries: [] }],
    ["기기 없음", { entries: [{ goal_id: goalId, day: "2026-11-05" }] }],
    [
      "모르는 칸",
      {
        device_id: mine,
        entries: [{ goal_id: goalId, day: "2026-11-05", minutes: 0 }],
      },
    ],
    [
      "날짜 모양",
      { device_id: mine, entries: [{ goal_id: goalId, day: "2026-11-5" }] },
    ],
    [
      "중복",
      {
        device_id: mine,
        entries: [
          { goal_id: goalId, day: "2026-11-05" },
          { goal_id: goalId, day: "2026-11-05" },
        ],
      },
    ],
  ];
  for (const [label, body] of cases) {
    const result = await call("POST", "/progress/remove", { token, body });
    assert.equal(result.status, 400, label);
  }
  assert.equal(
    (await call("POST", "/progress/remove", { body: {} })).status,
    401,
  );
  assert.equal((await call("GET", "/progress/remove", { token })).status, 405);
});
