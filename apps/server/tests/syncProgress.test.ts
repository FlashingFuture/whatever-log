import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DAY_MS,
  GOAL,
  type Json,
  setup,
  uuid,
} from "./helpers/syncFixtures.ts";

async function withGoal(name = "공부", sub = "sub-1") {
  const world = setup();
  const token = await world.signIn(sub);
  const goalId = uuid();
  await world.call("PUT", `/goals/${goalId}`, {
    token,
    body: { ...GOAL, name },
  });
  return { ...world, token, goalId };
}

const entry = (goalId: string, over: Record<string, unknown> = {}) => ({
  goal_id: goalId,
  day: "2026-11-05",
  minutes: 95,
  target_minutes: 120,
  ...over,
});

const days = (json: Json) => json.days as Json[];

test("기기가 보낸 달성도를 날짜 구간으로 읽는다(달성률 포함)", async () => {
  const { call, token, goalId } = await withGoal();
  const device = uuid();

  const put = await call("PUT", "/progress", {
    token,
    body: { device_id: device, entries: [entry(goalId)] },
  });

  assert.equal(put.status, 200);
  assert.deepEqual(put.json, { accepted: 1, ignored_goal_ids: [] });
  const read = await call("GET", "/progress?from=2026-11-01&to=2026-11-06", {
    token,
  });
  assert.deepEqual(read.json.days, [
    {
      goal_id: goalId,
      day: "2026-11-05",
      minutes: 95,
      target_minutes: 120,
      percent: 79,
      devices: 1,
    },
  ]);
  assert.equal(read.response.headers.get("Cache-Control"), "no-store");
});

test("같은 기기가 다시 보내면 그 줄을 덮어쓴다", async () => {
  const { call, token, goalId } = await withGoal();
  const device = uuid();
  await call("PUT", "/progress", {
    token,
    body: { device_id: device, entries: [entry(goalId)] },
  });

  await call("PUT", "/progress", {
    token,
    body: { device_id: device, entries: [entry(goalId, { minutes: 130 })] },
  });

  const [row] = days(
    (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
      .json,
  );
  assert.equal(row.minutes, 130);
  assert.equal(row.percent, 108); // 목표를 넘길 수 있다
  assert.equal(row.devices, 1);
});

test("여러 기기의 달성 분은 합산되고, 목표량은 가장 최근에 보낸 기기의 값이다", async () => {
  const { call, token, goalId, clock } = await withGoal();
  const pc = uuid();
  const phone = uuid();
  await call("PUT", "/progress", {
    token,
    body: { device_id: pc, entries: [entry(goalId, { minutes: 60 })] },
  });
  clock.now = new Date(clock.now.getTime() + 60_000);
  await call("PUT", "/progress", {
    token,
    body: {
      device_id: phone,
      entries: [entry(goalId, { minutes: 30, target_minutes: 100 })],
    },
  });

  const [row] = days(
    (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
      .json,
  );

  assert.equal(row.minutes, 90);
  assert.equal(row.target_minutes, 100);
  assert.equal(row.percent, 90);
  assert.equal(row.devices, 2);
});

test("삭제됐거나 없는 목표의 줄은 저장하지 않고 알려 주며, 나머지는 저장한다", async () => {
  const { call, token, goalId } = await withGoal();
  const gone = uuid();
  const removed = uuid();
  await call("PUT", `/goals/${removed}`, {
    token,
    body: { ...GOAL, name: "지울 것" },
  });
  await call("DELETE", `/goals/${removed}`, { token });

  const put = await call("PUT", "/progress", {
    token,
    body: {
      device_id: uuid(),
      entries: [entry(goalId), entry(gone), entry(removed)],
    },
  });

  assert.equal(put.status, 200);
  assert.equal(put.json.accepted, 1);
  assert.deepEqual(
    [...put.json.ignored_goal_ids].sort(),
    [gone, removed].sort(),
  );
  assert.equal(
    days(
      (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
        .json,
    ).length,
    1,
  );
});

test("다른 사용자의 목표에는 달성도를 쓸 수 없다", async () => {
  const { call, token, goalId, signIn, sqlite } = await withGoal();
  const mallory = await signIn("sub-m", "m@example.com");

  const put = await call("PUT", "/progress", {
    token: mallory,
    body: { device_id: uuid(), entries: [entry(goalId)] },
  });

  assert.deepEqual(put.json, { accepted: 0, ignored_goal_ids: [goalId] });
  assert.equal(
    sqlite.prepare("SELECT COUNT(*) AS n FROM progress").get()?.n,
    0,
  );
  assert.deepEqual(
    days(
      (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
        .json,
    ),
    [],
  );
});

test("목표를 삭제하면 그 달성 줄도 사라지고 읽기에도 나오지 않는다", async () => {
  const { call, token, goalId, sqlite } = await withGoal();
  await call("PUT", "/progress", {
    token,
    body: { device_id: uuid(), entries: [entry(goalId)] },
  });

  await call("DELETE", `/goals/${goalId}`, { token });

  assert.equal(
    sqlite.prepare("SELECT COUNT(*) AS n FROM progress").get()?.n,
    0,
  );
  assert.deepEqual(
    days(
      (await call("GET", "/progress?from=2026-11-01&to=2026-11-06", { token }))
        .json,
    ),
    [],
  );
});

const INVALID: [string, (goalId: string) => Record<string, unknown>][] = [
  [
    "없는 날짜(2월 30일)",
    (g) => ({ entries: [entry(g, { day: "2026-02-30" })] }),
  ],
  ["형식이 다른 날짜", (g) => ({ entries: [entry(g, { day: "2026/11/05" })] })],
  ["하루 넘게 미래", (g) => ({ entries: [entry(g, { day: "2026-11-08" })] })],
  ["400일보다 오래됨", (g) => ({ entries: [entry(g, { day: "2025-09-01" })] })],
  ["1441분", (g) => ({ entries: [entry(g, { minutes: 1441 })] })],
  ["음수 분", (g) => ({ entries: [entry(g, { minutes: -1 })] })],
  ["소수 분", (g) => ({ entries: [entry(g, { minutes: 1.5 })] })],
  ["목표량 0", (g) => ({ entries: [entry(g, { target_minutes: 0 })] })],
  ["목표 id가 UUID가 아님", () => ({ entries: [entry("abc")] })],
  ["같은 목표·날짜 중복", (g) => ({ entries: [entry(g), entry(g)] })],
  ["빈 목록", () => ({ entries: [] })],
  ["entries가 목록이 아님", () => ({ entries: "x" })],
  [
    "모르는 칸(프로세스)",
    (g) => ({ entries: [entry(g, { process: "chrome.exe" })] }),
  ],
  ["최상위 모르는 칸", (g) => ({ entries: [entry(g)], hostname: "MY-PC" })],
  [
    "기기 id가 UUID가 아님",
    (g) => ({ device_id: "MY-PC", entries: [entry(g)] }),
  ],
];

test("잘못된 달성도 요청은 400이고 아무것도 저장하지 않는다", async () => {
  const { call, token, goalId, sqlite } = await withGoal();

  for (const [label, build] of INVALID) {
    const result = await call("PUT", "/progress", {
      token,
      body: { device_id: uuid(), ...build(goalId) },
    });

    assert.equal(result.status, 400, label);
  }
  assert.equal(
    sqlite.prepare("SELECT COUNT(*) AS n FROM progress").get()?.n,
    0,
  );
});

test("날짜 경계: 오늘·내일(시간대 차이)·정확히 400일 전은 받는다", async () => {
  const { call, token, goalId } = await withGoal();
  const oldest = new Date(Date.UTC(2026, 10, 6) - 400 * DAY_MS)
    .toISOString()
    .slice(0, 10);

  const put = await call("PUT", "/progress", {
    token,
    body: {
      device_id: uuid(),
      entries: [
        entry(goalId, { day: "2026-11-06" }),
        entry(goalId, { day: "2026-11-07" }),
        entry(goalId, { day: oldest }),
      ],
    },
  });

  assert.equal(put.status, 200);
  assert.equal(put.json.accepted, 3);
});

test("한 번에 50줄까지 받고 51줄은 거부한다", async () => {
  const { call, token, goalId } = await withGoal();
  const make = (n: number) =>
    Array.from({ length: n }, (_, index) =>
      entry(goalId, {
        day: new Date(Date.UTC(2026, 7, 1) + index * DAY_MS)
          .toISOString()
          .slice(0, 10),
      }),
    );

  assert.equal(
    (
      await call("PUT", "/progress", {
        token,
        body: { device_id: uuid(), entries: make(50) },
      })
    ).status,
    200,
  );
  assert.equal(
    (
      await call("PUT", "/progress", {
        token,
        body: { device_id: uuid(), entries: make(51) },
      })
    ).status,
    400,
  );
});

test("기기는 10대까지이고, 이미 연결된 기기는 계속 보낼 수 있다", async () => {
  const { call, token, goalId } = await withGoal();
  const devices = Array.from({ length: 10 }, () => uuid());
  for (const device of devices) {
    const ok = await call("PUT", "/progress", {
      token,
      body: { device_id: device, entries: [entry(goalId)] },
    });
    assert.equal(ok.status, 200);
  }

  const eleventh = await call("PUT", "/progress", {
    token,
    body: { device_id: uuid(), entries: [entry(goalId)] },
  });
  assert.equal(eleventh.status, 409);
  assert.equal(eleventh.json.error.code, "too_many_devices");
  const existing = await call("PUT", "/progress", {
    token,
    body: { device_id: devices[0], entries: [entry(goalId, { minutes: 10 })] },
  });
  assert.equal(existing.status, 200);

  // 기기를 지우면 자리가 난다.
  assert.equal(
    (await call("DELETE", `/devices/${devices[1]}`, { token })).status,
    204,
  );
  assert.equal(
    (
      await call("PUT", "/progress", {
        token,
        body: { device_id: uuid(), entries: [entry(goalId)] },
      })
    ).status,
    200,
  );
});

test("기기를 지우면 그 기기의 줄만 사라진다", async () => {
  const { call, token, goalId } = await withGoal();
  const pc = uuid();
  const phone = uuid();
  await call("PUT", "/progress", {
    token,
    body: { device_id: pc, entries: [entry(goalId, { minutes: 60 })] },
  });
  await call("PUT", "/progress", {
    token,
    body: { device_id: phone, entries: [entry(goalId, { minutes: 30 })] },
  });

  assert.equal(
    (await call("DELETE", `/devices/${phone}`, { token })).status,
    204,
  );
  assert.equal(
    (await call("DELETE", `/devices/${phone}`, { token })).status,
    204,
  ); // 다시 해도 같다

  const [row] = days(
    (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
      .json,
  );
  assert.equal(row.minutes, 60);
  assert.equal(row.devices, 1);
});

test("다른 사용자의 기기 id를 지우려 해도 내 데이터만 대상이다", async () => {
  const { call, token, goalId, signIn } = await withGoal();
  const device = uuid();
  await call("PUT", "/progress", {
    token,
    body: { device_id: device, entries: [entry(goalId)] },
  });
  const other = await signIn("sub-o", "o@example.com");

  await call("DELETE", `/devices/${device}`, { token: other });

  assert.equal(
    days(
      (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
        .json,
    ).length,
    1,
  );
});

test("조회 구간 검사: 형식, 순서, 400일, 모르는 파라미터", async () => {
  const { call, token } = await withGoal();
  const bad = [
    "/progress",
    "/progress?from=2026-11-01",
    "/progress?from=2026-11-06&to=2026-11-01",
    "/progress?from=2026-02-30&to=2026-03-01",
    "/progress?from=2025-01-01&to=2026-11-06",
    "/progress?from=2026-11-01&to=2026-11-06&device_id=x",
  ];
  for (const path of bad) {
    assert.equal((await call("GET", path, { token })).status, 400, path);
  }
  // 400일 구간(양 끝 포함 400일)은 받는다.
  assert.equal(
    (await call("GET", "/progress?from=2025-10-04&to=2026-11-06", { token }))
      .status,
    200,
  );
});

test("조회는 내 데이터만 준다", async () => {
  const { call, token, goalId, signIn } = await withGoal();
  await call("PUT", "/progress", {
    token,
    body: { device_id: uuid(), entries: [entry(goalId)] },
  });
  const other = await signIn("sub-o", "o@example.com");
  const otherGoal = uuid();
  await call("PUT", `/goals/${otherGoal}`, { token: other, body: GOAL });
  await call("PUT", "/progress", {
    token: other,
    body: { device_id: uuid(), entries: [entry(otherGoal, { minutes: 5 })] },
  });

  const mine = days(
    (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
      .json,
  );
  const theirs = days(
    (
      await call("GET", "/progress?from=2026-11-05&to=2026-11-05", {
        token: other,
      })
    ).json,
  );

  assert.deepEqual(
    mine.map((row) => row.minutes),
    [95],
  );
  assert.deepEqual(
    theirs.map((row) => row.minutes),
    [5],
  );
});

test("서버에 저장되는 칸에는 프로세스·사이트·기기 이름이 없다", async () => {
  const { sqlite } = await withGoal();

  const columns = (table: string) =>
    sqlite
      .prepare(`PRAGMA table_info(${table})`)
      .all()
      .map((row) => row.name);

  assert.deepEqual(columns("progress"), [
    "user_id",
    "goal_id",
    "device_id",
    "day",
    "minutes",
    "target_minutes",
    "updated_at",
  ]);
  assert.deepEqual(columns("goals"), [
    "user_id",
    "id",
    "name",
    "name_key",
    "daily_target_minutes",
    "weekdays",
    "revision",
    "created_at",
    "updated_at",
    "deleted_at",
  ]);
});

test("기기 수 제한은 확인과 삽입이 한 문장이라, 확인한 뒤 자리가 찬 경우에도 넘지 않는다", async () => {
  const { call, token, goalId, deps, sqlite } = await withGoal();
  for (let n = 0; n < 9; n += 1) {
    await call("PUT", "/progress", {
      token,
      body: { device_id: uuid(), entries: [entry(goalId)] },
    });
  }
  const real = deps.db;
  deps.db = {
    prepare: (sql: string) => real.prepare(sql),
    async batch(statements) {
      // 이 요청이 "9대 → 자리가 있다"고 확인한 뒤, 다른 새 기기가 마지막 자리를 먼저 차지한 상황
      sqlite.exec(
        `INSERT INTO progress (user_id, goal_id, device_id, day, minutes, target_minutes, updated_at)
         SELECT user_id, goal_id, '${uuid()}', day, 1, 120, 't' FROM progress LIMIT 1`,
      );
      return real.batch(statements);
    },
  };

  const late = await call("PUT", "/progress", {
    token,
    body: { device_id: uuid(), entries: [entry(goalId)] },
  });

  assert.equal(late.status, 409);
  assert.equal(late.json.error.code, "too_many_devices");
  assert.equal(
    (
      sqlite
        .prepare("SELECT COUNT(DISTINCT device_id) AS n FROM progress")
        .get() as { n: number }
    ).n,
    10,
  );
});

test("같은 시각에 서로 다른 목표량을 올려도 기기 ID가 큰 쪽으로 정해져 조회마다 같다", async () => {
  const { call, token, goalId, sqlite } = await withGoal();
  const low = "00000000-0000-4000-8000-0000000000aa";
  const high = "00000000-0000-4000-8000-0000000000bb";
  for (const [device, target] of [
    [high, 100],
    [low, 50],
  ] as const) {
    await call("PUT", "/progress", {
      token,
      body: {
        device_id: device,
        entries: [entry(goalId, { minutes: 10, target_minutes: target })],
      },
    });
  }
  sqlite.exec("UPDATE progress SET updated_at = '2026-11-06T03:00:00.000Z'"); // 같은 시각

  for (let n = 0; n < 3; n += 1) {
    const [row] = days(
      (await call("GET", "/progress?from=2026-11-05&to=2026-11-05", { token }))
        .json,
    );
    assert.equal(row.target_minutes, 100);
    assert.equal(row.minutes, 20);
  }
});
