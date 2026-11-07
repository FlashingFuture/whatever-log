import assert from "node:assert/strict";
import { test } from "node:test";

import { DAY_MS, GOAL, setup, uuid } from "./helpers/syncFixtures.ts";

test("토큰이 없거나 잘못됐거나 만료됐으면 401이고 데이터를 읽지 않는다", async () => {
  const { call, signIn, clock } = setup();
  const token = await signIn();

  const cases: [string, Parameters<typeof call>[2]][] = [
    ["없음", {}],
    ["모양이 다름", { token: "short" }],
    ["모르는 토큰", { token: "A".repeat(43) }],
    ["Bearer가 아님", { headers: { Authorization: `Basic ${token}` } }],
  ];
  for (const [label, options] of cases) {
    const result = await call("GET", "/goals", options);

    assert.equal(result.status, 401, label);
    assert.equal(result.response.headers.get("WWW-Authenticate"), "Bearer");
    assert.equal(result.json.error.code, "invalid_token");
  }

  clock.now = new Date(clock.now.getTime() + 31 * DAY_MS);
  assert.equal((await call("GET", "/goals", { token })).status, 401);
});

test("허용되지 않는 메서드는 토큰 없이도 405이고, 모르는 주소는 이 모듈이 처리하지 않는다", async () => {
  const { call } = setup();

  const wrong = await call("GET", "/account");
  assert.equal(wrong.status, 405);
  assert.equal(wrong.response.headers.get("Allow"), "DELETE");
  assert.equal((await call("POST", "/goals")).status, 405);
  assert.equal((await call("GET", "/nope")).status, null);
});

test("목표를 만들면 201이고 목록에 나온다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();
  const id = uuid();

  const created = await call("PUT", `/goals/${id}`, { token, body: GOAL });

  assert.equal(created.status, 201);
  assert.deepEqual(created.json, {
    id,
    deleted: false,
    name: "공부",
    daily_target_minutes: 120,
    weekdays: [0, 1, 2, 3, 4],
    revision: 1,
    updated_at: "2026-11-06T03:00:00.000Z",
  });
  assert.equal(created.response.headers.get("Cache-Control"), "no-store");
  const listed = await call("GET", "/goals", { token });
  assert.deepEqual(listed.json.goals, [created.json]);
});

test("같은 내용으로 만드는 요청을 다시 보내도 200으로 같은 결과이다(재시도 안전)", async () => {
  const { call, signIn } = setup();
  const token = await signIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: GOAL });

  const retry = await call("PUT", `/goals/${id}`, { token, body: GOAL });

  assert.equal(retry.status, 200);
  assert.equal(retry.json.revision, 1);
  assert.equal(
    ((await call("GET", "/goals", { token })).json.goals as unknown[]).length,
    1,
  );
});

test("같은 id를 다른 내용으로 만들려 하면 409와 서버의 현재 값을 돌려준다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: GOAL });

  const clash = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, daily_target_minutes: 30 },
  });

  assert.equal(clash.status, 409);
  assert.equal(clash.json.error.code, "conflict");
  assert.equal(clash.json.current.daily_target_minutes, 120);
});

test("수정은 현재 revision을 맞춰야 하고, 낡은 revision은 409이다", async () => {
  const { call, signIn, clock } = setup();
  const token = await signIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: GOAL });
  clock.now = new Date(clock.now.getTime() + 1000);

  const updated = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, name: "공부2", base_revision: 1 },
  });
  assert.equal(updated.status, 200);
  assert.equal(updated.json.revision, 2);
  assert.equal(updated.json.name, "공부2");
  assert.equal(updated.json.updated_at, "2026-11-06T03:00:01.000Z");

  const stale = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, name: "덮어쓰기", base_revision: 1 },
  });
  assert.equal(stale.status, 409);
  assert.equal(stale.json.error.code, "conflict");
  assert.equal(stale.json.current.name, "공부2");
  assert.equal(stale.json.current.revision, 2);
  // 낡은 요청이 조용히 덮어쓰지 않았다.
  assert.equal(
    (
      (await call("GET", "/goals", { token })).json.goals as { name: string }[]
    )[0].name,
    "공부2",
  );
});

test("없는 목표를 수정하려 하면 404이다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();

  const result = await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, base_revision: 1 },
  });

  assert.equal(result.status, 404);
});

test("대소문자·유니코드 표현만 다른 이름은 같은 이름으로 보고 거부한다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();
  await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, name: "Study" },
  });

  const second = await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, name: "STUDY" },
  });
  assert.equal(second.status, 409);
  assert.equal(second.json.error.code, "duplicate_name");

  // 수정으로 다른 목표의 이름과 겹치게 하는 것도 막는다.
  const other = uuid();
  await call("PUT", `/goals/${other}`, {
    token,
    body: { ...GOAL, name: "운동" },
  });
  const rename = await call("PUT", `/goals/${other}`, {
    token,
    body: { ...GOAL, name: "study", base_revision: 1 },
  });
  assert.equal(rename.status, 409);
  assert.equal(rename.json.error.code, "duplicate_name");
});

test("목표는 20개까지이고, 삭제한 목표는 세지 않는다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();
  const ids: string[] = [];
  for (let n = 0; n < 20; n += 1) {
    ids.push(uuid());
    const result = await call("PUT", `/goals/${ids[n]}`, {
      token,
      body: { ...GOAL, name: `목표${n}` },
    });
    assert.equal(result.status, 201, `${n}`);
  }

  const over = await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, name: "21번째" },
  });
  assert.equal(over.status, 409);
  assert.equal(over.json.error.code, "too_many_goals");

  await call("DELETE", `/goals/${ids[0]}`, { token });
  const again = await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, name: "21번째" },
  });
  assert.equal(again.status, 201);
});

const INVALID: [string, Record<string, unknown>][] = [
  ["이름이 비어 있음", { name: "" }],
  ["이름이 51자", { name: "가".repeat(51) }],
  ["이름에 줄바꿈", { name: "공\n부" }],
  ["이름에 폭 없는 공백", { name: "공​부" }],
  ["이름 앞뒤 공백", { name: " 공부" }],
  ["NFC가 아닌 이름", { name: "한" }],
  ["이름이 문자열이 아님", { name: 5 }],
  ["목표 0분", { daily_target_minutes: 0 }],
  ["목표 1441분", { daily_target_minutes: 1441 }],
  ["목표가 소수", { daily_target_minutes: 1.5 }],
  ["목표가 문자열", { daily_target_minutes: "60" }],
  ["목표가 불리언", { daily_target_minutes: true }],
  ["요일이 비어 있음", { weekdays: [] }],
  ["요일 7", { weekdays: [7] }],
  ["요일 중복", { weekdays: [1, 1] }],
  ["요일이 목록이 아님", { weekdays: "1" }],
  ["base_revision 음수", { base_revision: -1 }],
  ["base_revision 소수", { base_revision: 0.5 }],
  ["모르는 칸", { processes: ["chrome.exe"] }],
];

test("잘못된 입력은 400이다 — 프로세스 같은 모르는 칸도 거부한다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();

  for (const [label, override] of INVALID) {
    const result = await call("PUT", `/goals/${uuid()}`, {
      token,
      body: { ...GOAL, ...override },
    });

    assert.equal(result.status, 400, label);
    assert.equal(result.json.error.code, "invalid_request", label);
  }
  assert.deepEqual((await call("GET", "/goals", { token })).json.goals, []);
});

test("경계값은 받는다: 이름 50자, 1분, 1440분, 일곱 요일", async () => {
  const { call, signIn } = setup();
  const token = await signIn();

  for (const body of [
    { ...GOAL, name: "가".repeat(50) },
    { ...GOAL, name: "a", daily_target_minutes: 1 },
    {
      ...GOAL,
      name: "b",
      daily_target_minutes: 1440,
      weekdays: [0, 1, 2, 3, 4, 5, 6],
    },
  ]) {
    assert.equal(
      (await call("PUT", `/goals/${uuid()}`, { token, body })).status,
      201,
    );
  }
});

test("주소의 id가 UUID가 아니면 404이다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();

  assert.equal(
    (await call("PUT", "/goals/not-a-uuid", { token, body: GOAL })).status,
    404,
  );
  assert.equal((await call("DELETE", "/goals/1", { token })).status, 404);
});

test("본문 형식·크기가 맞지 않으면 415/413/400이다", async () => {
  const { call, signIn, deps } = setup();
  const token = await signIn();
  const id = uuid();
  const headers = (type?: string) => {
    const h = new Headers({ Authorization: `Bearer ${token}` });
    if (type) h.set("Content-Type", type);
    return h;
  };
  const send = async (init: RequestInit) => {
    const { handleApi } = await import("../src/sync/api.ts");
    const request = new Request(`https://server.example/goals/${id}`, {
      method: "PUT",
      ...init,
    });
    return (await handleApi(request, new URL(request.url), deps)) as Response;
  };

  assert.equal(
    (await send({ headers: headers("text/plain"), body: "{}" })).status,
    415,
  );
  assert.equal(
    (
      await send({
        headers: headers("application/json"),
        body: "x".repeat(2000),
      })
    ).status,
    413,
  );
  assert.equal(
    (await send({ headers: headers("application/json"), body: "{not json" }))
      .status,
    400,
  );
  assert.equal(
    (await send({ headers: headers("application/json"), body: "" })).status,
    400,
  );
  assert.equal((await call("GET", "/goals", { token })).status, 200);
});

test("사용자끼리는 서로의 목표를 볼 수도 고칠 수도 없고, 같은 id를 각자 쓸 수 있다", async () => {
  const { call, signIn } = setup();
  const alice = await signIn("sub-a", "a@example.com");
  const bob = await signIn("sub-b", "b@example.com");
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token: alice, body: GOAL });

  assert.deepEqual(
    (await call("GET", "/goals", { token: bob })).json.goals,
    [],
  );
  assert.equal(
    (
      await call("PUT", `/goals/${id}`, {
        token: bob,
        body: { ...GOAL, name: "남의 것", base_revision: 1 },
      })
    ).status,
    404,
  );
  assert.equal(
    (await call("DELETE", `/goals/${id}`, { token: bob })).status,
    404,
  );
  // 같은 UUID를 밥이 새 목표로 만들 수 있고, 그것이 앨리스의 목표에 영향을 주지 않는다.
  assert.equal(
    (
      await call("PUT", `/goals/${id}`, {
        token: bob,
        body: { ...GOAL, name: "밥의 것" },
      })
    ).status,
    201,
  );
  assert.equal(
    (
      (await call("GET", "/goals", { token: alice })).json.goals as {
        name: string;
      }[]
    )[0].name,
    "공부",
  );
});

test("삭제하면 이름은 지워지고 삭제 표시만 남으며, 이름을 다시 쓸 수 있다", async () => {
  const { call, signIn, sqlite } = setup();
  const token = await signIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: GOAL });

  const deleted = await call("DELETE", `/goals/${id}`, { token });

  assert.equal(deleted.status, 204);
  const [goal] = (await call("GET", "/goals", { token })).json.goals as Record<
    string,
    unknown
  >[];
  assert.deepEqual(goal, {
    id,
    deleted: true,
    revision: 2,
    updated_at: "2026-11-06T03:00:00.000Z",
  });
  assert.equal(sqlite.prepare("SELECT name FROM goals").get()?.name, "");
  assert.equal(
    (await call("PUT", `/goals/${uuid()}`, { token, body: GOAL })).status,
    201,
  );
});

test("삭제는 여러 번 보내도 204이고, 삭제된 목표를 수정하면 409 goal_deleted이다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: GOAL });
  await call("DELETE", `/goals/${id}`, { token });

  assert.equal((await call("DELETE", `/goals/${id}`, { token })).status, 204);
  const edit = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, base_revision: 2 },
  });
  assert.equal(edit.status, 409);
  assert.equal(edit.json.error.code, "goal_deleted");
  const recreate = await call("PUT", `/goals/${id}`, { token, body: GOAL });
  assert.equal(recreate.status, 409);
  assert.equal(recreate.json.error.code, "goal_deleted");
});

test("삭제 표시는 30일 뒤 다음 삭제 때 정리된다", async () => {
  const { call, signIn, clock, sqlite } = setup();
  const token = await signIn();
  const first = uuid();
  const second = uuid();
  await call("PUT", `/goals/${first}`, { token, body: GOAL });
  await call("PUT", `/goals/${second}`, {
    token,
    body: { ...GOAL, name: "운동" },
  });
  await call("DELETE", `/goals/${first}`, { token });

  clock.now = new Date(clock.now.getTime() + 29 * DAY_MS);
  await call("DELETE", `/goals/${second}`, { token });
  assert.equal(sqlite.prepare("SELECT COUNT(*) AS n FROM goals").get()?.n, 2); // 아직 30일 전

  clock.now = new Date(clock.now.getTime() + 2 * DAY_MS);
  const later = await signIn(); // 처음 토큰은 30일이면 만료된다
  const third = uuid();
  await call("PUT", `/goals/${third}`, {
    token: later,
    body: { ...GOAL, name: "산책" },
  });
  await call("DELETE", `/goals/${third}`, { token: later });

  const ids = sqlite
    .prepare("SELECT id FROM goals")
    .all()
    .map((row) => row.id);
  assert.ok(!ids.includes(first), "30일이 지난 삭제 표시는 정리된다");
});

test("로그아웃은 이 토큰만 폐기한다", async () => {
  const { call, signIn } = setup();
  const phone = await signIn();
  const laptop = await signIn();

  assert.equal(
    (await call("POST", "/auth/logout", { token: phone })).status,
    204,
  );

  assert.equal((await call("GET", "/goals", { token: phone })).status, 401);
  assert.equal((await call("GET", "/goals", { token: laptop })).status, 200);
});

test("계정을 삭제하면 사용자·목표·달성도·토큰이 모두 사라지고 다른 사용자는 그대로이다", async () => {
  const { call, signIn, sqlite } = setup();
  const alice = await signIn("sub-a", "a@example.com");
  const bob = await signIn("sub-b", "b@example.com");
  const goalA = uuid();
  const goalB = uuid();
  await call("PUT", `/goals/${goalA}`, { token: alice, body: GOAL });
  await call("PUT", `/goals/${goalB}`, { token: bob, body: GOAL });
  const entry = { day: "2026-11-05", minutes: 30, target_minutes: 120 };
  await call("PUT", "/progress", {
    token: alice,
    body: { device_id: uuid(), entries: [{ goal_id: goalA, ...entry }] },
  });
  await call("PUT", "/progress", {
    token: bob,
    body: { device_id: uuid(), entries: [{ goal_id: goalB, ...entry }] },
  });

  const result = await call("DELETE", "/account", { token: alice });

  assert.equal(result.status, 204);
  assert.equal((await call("GET", "/goals", { token: alice })).status, 401);
  const count = (table: string) =>
    sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get()?.n;
  assert.deepEqual(
    [count("users"), count("goals"), count("progress"), count("tokens")],
    [1, 1, 1, 1],
  );
  assert.equal(
    ((await call("GET", "/goals", { token: bob })).json.goals as unknown[])
      .length,
    1,
  );
});

test("읽은 뒤 쓰기 전에 다른 기기가 먼저 고쳐도 덮어쓰지 않고 409이다(경합)", async () => {
  const { call, signIn, deps, sqlite } = setup();
  const token = await signIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: GOAL });
  const real = deps.db;
  deps.db = {
    prepare(sql: string) {
      if (sql.startsWith("UPDATE goals SET name")) {
        // 이 기기가 UPDATE를 보내기 직전에 다른 기기의 수정이 먼저 들어온 상황
        sqlite.exec(
          "UPDATE goals SET name = '다른 기기', name_key = '다른 기기', revision = revision + 1",
        );
      }
      return real.prepare(sql);
    },
    batch: (statements) => real.batch(statements),
  };

  const result = await call("PUT", `/goals/${id}`, {
    token,
    body: { ...GOAL, name: "내 수정", base_revision: 1 },
  });

  assert.equal(result.status, 409);
  assert.equal(result.json.error.code, "conflict");
  assert.equal(result.json.current.name, "다른 기기");
  assert.equal(
    sqlite.prepare("SELECT name FROM goals").get()?.name,
    "다른 기기",
  );
});

test("30일이 지난 삭제 표시는 다른 목표를 지우지 않아도 목록을 읽을 때 정리된다", async () => {
  const { call, signIn, clock, sqlite } = setup();
  const token = await signIn();
  const id = uuid();
  await call("PUT", `/goals/${id}`, { token, body: GOAL });
  await call("DELETE", `/goals/${id}`, { token });
  assert.equal(
    (sqlite.prepare("SELECT COUNT(*) AS n FROM goals").get() as { n: number })
      .n,
    1,
  );

  clock.now = new Date(clock.now.getTime() + 31 * DAY_MS);
  const later = await signIn(); // 처음 토큰은 30일이면 만료된다
  const listed = await call("GET", "/goals", { token: later });

  assert.deepEqual(listed.json.goals, []);
  assert.equal(
    (sqlite.prepare("SELECT COUNT(*) AS n FROM goals").get() as { n: number })
      .n,
    0,
  );
});

test("이름 비교는 파이썬 casefold처럼 접는다: Straße와 STRASSE는 같은 이름이다", async () => {
  const { call, signIn } = setup();
  const token = await signIn();
  await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, name: "Straße" },
  });

  const clash = await call("PUT", `/goals/${uuid()}`, {
    token,
    body: { ...GOAL, name: "STRASSE" },
  });

  assert.equal(clash.status, 409);
  assert.equal(clash.json.error.code, "duplicate_name");
});

test("서버의 이름 키는 로컬 casefold와 같은 접기를 한다", async () => {
  const { nameKey } = await import("../src/sync/goalInput.ts");

  // 값은 파이썬 "...".casefold()의 결과다(packages/goals의 name_key와 같아야 두 기기가 같은 목표를 같은 이름으로 본다).
  for (const [name, folded] of [
    ["Straße", "strasse"],
    ["ΣΊΣΥΦΟΣ", "σίσυφοσ"],
    ["ﬁle", "file"],
    ["Ǆ", "ǆ"],
    ["공부", "공부"],
  ]) {
    assert.equal(nameKey(name), folded, name);
  }
});

test("이름 키는 파이썬 casefold와 어긋나기 쉬운 글자까지 맞춘다(İ, ǅ, ſ, 어말 시그마)", async () => {
  const { nameKey } = await import("../src/sync/goalInput.ts");

  for (const [name, folded] of [
    ["İ", "i̇"],
    ["ǅ", "ǆ"],
    ["ſ", "s"],
    ["ΟΔΟΣ", "οδοσ"],
  ]) {
    assert.equal(nameKey(name), folded, name);
  }
});
