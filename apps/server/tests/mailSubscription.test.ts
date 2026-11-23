import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { type Env } from "../src/index.ts";
import { LIMITS } from "../src/mail/config.ts";
import { signUnsubscribe, verifyUnsubscribe } from "../src/mail/links.ts";
import type { MailMessage, SendResult } from "../src/mail/port.ts";
import { userKey } from "../src/mail/quota.ts";
import {
  putSubscription,
  setSubscriptionStatus,
} from "../src/mail/subscriptions.ts";
import { addressHash } from "../src/mail/suppression.ts";
import { GOAL, type Json, setup, uuid } from "./helpers/syncFixtures.ts";

const SECRET = "link-secret-for-tests";
const BASE = "https://server.example";
const WEBHOOK_KEY = new Uint8Array(24).map((_, i) => i + 1);
const WEBHOOK_SECRET = `whsec_${btoa(String.fromCharCode(...WEBHOOK_KEY))}`;

class FakeMail {
  sent: MailMessage[] = [];
  result: SendResult = { ok: true, id: "msg-1" };
  async send(message: MailMessage): Promise<SendResult> {
    this.sent.push(message);
    return this.result;
  }
}

const SCHEDULE = {
  frequency: "weekly",
  weekday: 0,
  send_time: "09:00",
  timezone: "Asia/Seoul",
};

async function world(options: { links?: boolean } = {}) {
  const fixture = setup();
  const port = new FakeMail();
  fixture.deps.mail = () => ({
    port,
    sender: { from: "whatever.log <reports@example.com>", mode: "domain" },
    links:
      options.links === false ? undefined : { secret: SECRET, baseUrl: BASE },
  });
  const token = await fixture.signIn("sub-1", "person@example.com");
  const goal = uuid();
  await fixture.call("PUT", `/goals/${goal}`, { token, body: GOAL });
  const other = uuid();
  await fixture.call("PUT", `/goals/${other}`, {
    token,
    body: { ...GOAL, name: "운동" },
  });
  const subscribe = (body: Json = {}, as = token) =>
    fixture.call("PUT", "/mail/subscription", {
      token: as,
      body: { goal_id: goal, ...SCHEDULE, ...body },
    });
  const env: Env = {
    GOOGLE_CLIENT_ID: "client",
    GOOGLE_CLIENT_SECRET: "secret",
    DB: fixture.db as never,
    MAIL_LINK_SECRET: SECRET,
    RESEND_WEBHOOK_SECRET: WEBHOOK_SECRET,
    SERVER_PUBLIC_URL: BASE,
  };
  const publicCall = (request: Request, overrides: Partial<Env> = {}) =>
    worker.fetch(request, { ...env, ...overrides }, {} as never);
  return { ...fixture, port, token, goal, other, subscribe, env, publicCall };
}

const subscriptionId = (sqlite: ReturnType<typeof setup>["sqlite"]) =>
  (sqlite.prepare("SELECT id FROM mail_subscriptions").get() as Json)
    .id as string;

// --- 신청·조회 ---

test("신청하면 201이고 조회에 나온다(구독 id는 응답에 싣지 않는다)", async () => {
  const { call, token, subscribe, goal } = await world();

  const created = await subscribe();

  assert.equal(created.status, 201);
  assert.equal(created.json.created, true);
  assert.deepEqual(
    {
      ...created.json.subscription,
      created_at: undefined,
      updated_at: undefined,
    },
    {
      goal_id: goal,
      frequency: "weekly",
      weekday: 0,
      day_of_month: null,
      send_time: "09:00",
      timezone: "Asia/Seoul",
      status: "active",
      ended_reason: null,
      created_at: undefined,
      updated_at: undefined,
    },
  );
  assert.ok(!("id" in created.json.subscription));
  const read = await call("GET", "/mail/subscription", { token });
  assert.deepEqual(read.json, {
    subscription: created.json.subscription,
    daily_available: true,
  });
});

test("신청하지 않았으면 조회는 null이다. 로그인하지 않았으면 401이다", async () => {
  const fixture = setup();
  const token = await fixture.signIn();
  assert.deepEqual(
    (await fixture.call("GET", "/mail/subscription", { token })).json,
    { subscription: null, daily_available: true },
  );
  assert.equal((await fixture.call("GET", "/mail/subscription")).status, 401);
  assert.equal(
    (await fixture.call("POST", "/mail/subscription", { token })).status,
    405,
  );
});

test("주기에 맞는 칸만 받는다(매일·매주·매월), 틀리면 400이고 저장하지 않는다", async () => {
  const { subscribe, sqlite } = await world();
  const cases: [string, Json][] = [
    ["매일에 요일", { frequency: "daily", weekday: 1 }],
    ["매주에 요일 없음", { frequency: "weekly", weekday: null }],
    ["매주에 일자", { frequency: "weekly", day_of_month: 3 }],
    ["매월 29일", { frequency: "monthly", weekday: null, day_of_month: 29 }],
    ["매월 0일", { frequency: "monthly", weekday: null, day_of_month: 0 }],
    ["모르는 주기", { frequency: "hourly" }],
    ["24시", { send_time: "24:00" }],
    ["초까지", { send_time: "09:00:00" }],
    ["한 자리 시", { send_time: "9:00" }],
    ["모르는 시간대", { timezone: "Mars/Olympus" }],
    ["시간대 모양", { timezone: "../etc" }],
    ["목표 id 모양", { goal_id: "goal-1" }],
    ["모르는 칸", { email: "victim@example.org" }],
    ["replace 모양", { replace: "yes" }],
  ];
  for (const [label, body] of cases) {
    const result = await subscribe(body);
    assert.equal(result.status, 400, label);
  }
  assert.equal(
    (
      sqlite
        .prepare("SELECT COUNT(*) AS n FROM mail_subscriptions")
        .get() as Json
    ).n,
    0,
  );
});

test("매일·매월도 신청할 수 있다", async () => {
  const daily = await (await world()).subscribe({
    frequency: "daily",
    weekday: null,
  });
  assert.equal(daily.status, 201);
  const monthly = await (await world()).subscribe({
    frequency: "monthly",
    weekday: null,
    day_of_month: 28,
    timezone: "UTC",
  });
  assert.equal(monthly.status, 201);
  assert.equal(monthly.json.subscription.day_of_month, 28);
});

// --- 가드: 목표 ---

test("서버에 없는(남의, 지운) 목표에는 신청할 수 없다", async () => {
  const { subscribe, call, token, signIn, goal } = await world();
  assert.equal(
    (await subscribe({ goal_id: uuid() })).json.error.code,
    "goal_not_found",
  );

  const stranger = await signIn("sub-2", "b@example.com");
  const result = await subscribe({}, stranger); // 남의 목표 id
  assert.equal(result.status, 404);

  await call("DELETE", `/goals/${goal}`, { token });
  assert.equal((await subscribe()).status, 404);
});

test("기간이 끝난 목표에는 신청할 수 없다(그 사용자의 시간대 기준 오늘)", async () => {
  const { call, token, clock } = await world();
  clock.now = new Date("2026-11-30T16:00:00.000Z"); // 서울은 12월 1일 01:00, UTC는 11월 30일
  const ended = uuid();
  await call("PUT", `/goals/${ended}`, {
    token,
    body: {
      ...GOAL,
      name: "지난 목표",
      start_date: "2026-11-01",
      end_date: "2026-11-30",
    },
  });
  const body = { goal_id: ended, ...SCHEDULE };

  const seoul = await call("PUT", "/mail/subscription", { token, body });
  assert.equal(seoul.status, 409);
  assert.equal(seoul.json.error.code, "goal_ended");

  const utc = await call("PUT", "/mail/subscription", {
    token,
    body: { ...body, timezone: "UTC" },
  });
  assert.equal(utc.status, 201); // UTC로는 아직 마지막 날이다
});

// --- 사용자당 하나 ---

test("다른 목표를 구독 중이면 409와 지금 구독을 돌려주고, replace면 옮긴다(같은 구독)", async () => {
  const { subscribe, other, goal, sqlite } = await world();
  await subscribe();
  const id = subscriptionId(sqlite);

  const asked = await subscribe({ goal_id: other });
  assert.equal(asked.status, 409);
  assert.equal(asked.json.error.code, "subscription_exists");
  assert.equal(asked.json.current.goal_id, goal);

  const moved = await subscribe({ goal_id: other, replace: true });
  assert.equal(moved.status, 200);
  assert.equal(moved.json.created, false);
  assert.equal(moved.json.subscription.goal_id, other);
  assert.equal(subscriptionId(sqlite), id);
  assert.equal(
    (
      sqlite
        .prepare("SELECT COUNT(*) AS n FROM mail_subscriptions")
        .get() as Json
    ).n,
    1,
  );
});

test("같은 목표의 일정을 바꾸는 것은 묻지 않는다", async () => {
  const { subscribe } = await world();
  await subscribe();
  const changed = await subscribe({ weekday: 4, send_time: "21:30" });
  assert.equal(changed.status, 200);
  assert.deepEqual(
    [changed.json.subscription.weekday, changed.json.subscription.send_time],
    [4, "21:30"],
  );
});

test("사용자당 하나는 DB 제약이 지킨다(가드를 거치지 않아도 두 번째 줄은 들어가지 않는다)", async () => {
  const { subscribe, sqlite, other } = await world();
  await subscribe();
  const userId = (
    sqlite.prepare("SELECT user_id FROM mail_subscriptions").get() as Json
  ).user_id;
  assert.throws(
    () =>
      sqlite
        .prepare(
          "INSERT INTO mail_subscriptions (id, user_id, goal_id, frequency, weekday, send_time, timezone, status, created_at, updated_at) " +
            "VALUES (?, ?, ?, 'weekly', 0, '09:00', 'UTC', 'active', 't', 't')",
        )
        .run(uuid(), userId, other),
    /UNIQUE/,
  );
});

// --- 매일 상한 ---

function fillDaily(
  sqlite: ReturnType<typeof setup>["sqlite"],
  count: number,
  prefix = "",
) {
  for (let i = 0; i < count; i++) {
    const user = sqlite
      .prepare(
        "INSERT INTO users (google_sub, email, created_at, updated_at) VALUES (?, ?, 't', 't') RETURNING id",
      )
      .get(`filler-${prefix}${i}`, `f${prefix}${i}@example.com`) as Json;
    const goal = uuid();
    sqlite
      .prepare(
        "INSERT INTO goals (user_id, id, name, name_key, daily_target_minutes, weekdays, revision, created_at, updated_at) VALUES (?, ?, 'g', 'g', 30, 1, 1, 't', 't')",
      )
      .run(user.id, goal);
    sqlite
      .prepare(
        "INSERT INTO mail_subscriptions (id, user_id, goal_id, frequency, send_time, timezone, status, created_at, updated_at) VALUES (?, ?, ?, 'daily', '09:00', 'UTC', 'active', 't', 't')",
      )
      .run(uuid(), user.id, goal);
  }
}

test("매일 구독자가 상한이면 매일은 409이고 매주·매월은 된다", async () => {
  const { subscribe, call, token, sqlite } = await world();
  fillDaily(sqlite, LIMITS.dailySubscribers);

  const daily = await subscribe({ frequency: "daily", weekday: null });
  assert.equal(daily.status, 409);
  assert.equal(daily.json.error.code, "daily_full");
  assert.equal(
    (await call("GET", "/mail/subscription", { token })).json.daily_available,
    false,
  );
  assert.equal((await subscribe()).status, 201);
});

test("이미 매일인 사용자는 상한이어도 시각을 바꿀 수 있고, 꺼진 매일 구독을 다시 켜는 것은 상한을 본다", async () => {
  const { subscribe, call, token, sqlite } = await world();
  await subscribe({ frequency: "daily", weekday: null });
  fillDaily(sqlite, LIMITS.dailySubscribers - 1);

  const retimed = await subscribe({
    frequency: "daily",
    weekday: null,
    send_time: "07:00",
  });
  assert.equal(retimed.status, 200);

  await call("PATCH", "/mail/subscription", {
    token,
    body: { status: "paused" },
  });
  fillDaily(sqlite, 1, "late-"); // 쉬는 사이 자리가 찼다
  const resumed = await call("PATCH", "/mail/subscription", {
    token,
    body: { status: "active" },
  });
  assert.equal(resumed.status, 409);
  assert.equal(resumed.json.error.code, "daily_full");
});

// --- 켜고 끄기, 지우기 ---

test("끄고 다시 켤 수 있다. 끝난 구독은 다시 켤 수 없고 새로 신청한다", async () => {
  const { subscribe, call, token, goal } = await world();
  await subscribe();

  const paused = await call("PATCH", "/mail/subscription", {
    token,
    body: { status: "paused" },
  });
  assert.equal(paused.json.subscription.status, "paused");
  const active = await call("PATCH", "/mail/subscription", {
    token,
    body: { status: "active" },
  });
  assert.equal(active.json.subscription.status, "active");

  await call("DELETE", `/goals/${goal}`, { token });
  const ended = await call("PATCH", "/mail/subscription", {
    token,
    body: { status: "active" },
  });
  assert.equal(ended.status, 409);
  assert.equal(ended.json.error.code, "subscription_ended");
  assert.equal(
    (
      await call("PATCH", "/mail/subscription", {
        token,
        body: { status: "ended" },
      })
    ).status,
    400,
  );
});

test("지우면 204이고 다시 지우면 404이다", async () => {
  const { subscribe, call, token } = await world();
  await subscribe();
  assert.equal(
    (await call("DELETE", "/mail/subscription", { token })).status,
    204,
  );
  assert.equal(
    (await call("DELETE", "/mail/subscription", { token })).status,
    404,
  );
  assert.equal(
    (await call("GET", "/mail/subscription", { token })).json.subscription,
    null,
  );
});

test("목표를 지우면 구독이 끝나고(goal_deleted) 다른 목표로 새로 신청할 수 있다", async () => {
  const { subscribe, call, token, goal, other } = await world();
  await subscribe();

  await call("DELETE", `/goals/${goal}`, { token });
  const read = (await call("GET", "/mail/subscription", { token })).json;
  assert.deepEqual(
    [read.subscription.status, read.subscription.ended_reason],
    ["ended", "goal_deleted"],
  );

  const again = await subscribe({ goal_id: other }); // 끝난 구독은 묻지 않고 바꾼다
  assert.equal(again.status, 200);
  assert.equal(again.json.subscription.status, "active");
});

// --- 첫 신청 확인 메일 ---

test("첫 신청에 확인 메일을 본인 주소로 한 통 보내고, 수신 거부 헤더와 서명 링크가 있다", async () => {
  const { subscribe, port, sqlite } = await world();

  const created = await subscribe();

  assert.equal(created.json.welcome, "sent");
  assert.equal(port.sent.length, 1);
  const [message] = port.sent;
  const id = subscriptionId(sqlite);
  assert.equal(message.to, "person@example.com");
  assert.equal(message.idempotencyKey, `welcome-${id}`);
  assert.match(message.text, /"공부" 목표/);
  assert.match(message.text, /매주 월요일 09:00 \(Asia\/Seoul\)/);
  const link = new URL(
    (message.headers?.["List-Unsubscribe"] ?? "").replace(/^<|>$/g, ""),
  );
  assert.equal(link.origin + link.pathname, `${BASE}/mail/unsubscribe`);
  assert.equal(link.searchParams.get("s"), id);
  assert.ok(
    await verifyUnsubscribe(SECRET, id, link.searchParams.get("t") ?? ""),
  );
  assert.equal(
    message.headers?.["List-Unsubscribe-Post"],
    "List-Unsubscribe=One-Click",
  );
  assert.ok(message.text.includes(link.href));
});

test("확인 메일은 Google 계정당 한 번이다(바꾸기·지우고 다시 신청·계정 삭제 후 재가입에도)", async () => {
  const { subscribe, call, token, port, signIn } = await world();
  await subscribe();
  assert.equal(
    (await subscribe({ send_time: "10:00" })).json.welcome,
    "already",
  );
  await call("DELETE", "/mail/subscription", { token });
  assert.equal((await subscribe()).json.welcome, "already");

  await call("DELETE", "/account", { token });
  const again = await signIn("sub-1", "person@example.com");
  const goal = uuid();
  await call("PUT", `/goals/${goal}`, { token: again, body: GOAL });
  const fresh = await call("PUT", "/mail/subscription", {
    token: again,
    body: { goal_id: goal, ...SCHEDULE },
  });
  assert.equal(fresh.json.welcome, "already");
  assert.equal(port.sent.length, 1);
});

test("링크 설정이 없으면 구독은 저장하고 확인 메일만 미룬다(다음 신청 때 보낸다)", async () => {
  const fixture = await world({ links: false });
  const first = await fixture.subscribe();
  assert.equal(first.status, 201);
  assert.equal(first.json.welcome, "not_configured");
  assert.equal(fixture.port.sent.length, 0);
});

test("확인 메일이 확실히 실패하면 자리를 돌려주고 다음에 다시 보낸다. 같은 구독이면 같은 멱등 키다", async () => {
  const { subscribe, port, sqlite } = await world();
  port.result = { ok: false, reason: "rejected", retryable: false };

  assert.equal((await subscribe()).json.welcome, "failed");
  assert.equal(
    (sqlite.prepare("SELECT COUNT(*) AS n FROM mail_sends").get() as Json).n,
    0,
  );

  port.result = { ok: true, id: "msg-2" };
  assert.equal((await subscribe({ send_time: "10:00" })).json.welcome, "sent");
  assert.equal(port.sent[0].idempotencyKey, port.sent[1].idempotencyKey);
});

test("응답을 확인하지 못한 실패는 자리를 유지해 같은 날 다시 보내지 않는다", async () => {
  const { subscribe, port } = await world();
  port.result = { ok: false, reason: "unavailable", retryable: true };
  assert.equal((await subscribe()).json.welcome, "failed");
  assert.equal(
    (await subscribe({ send_time: "10:00" })).json.welcome,
    "limited",
  );
  assert.equal(port.sent.length, 1);
});

test("확인 메일 기록은 계정과 무관한 키로 남는다(주소는 없다)", async () => {
  const { subscribe, sqlite } = await world();
  await subscribe();
  const rows = sqlite.prepare("SELECT * FROM mail_welcomes").all() as Json[];
  assert.deepEqual(Object.keys(rows[0]).sort(), ["user_key", "welcomed_at"]);
  assert.equal(rows[0].user_key, await userKey("sub-1"));
});

// --- 보내지 않을 주소 ---

test("반송·신고된 주소는 신청할 수 없지만 조회·끄기·지우기는 된다", async () => {
  const { subscribe, call, token, sqlite } = await world();
  await subscribe();
  sqlite
    .prepare(
      "INSERT INTO mail_suppressions (address_hash, reason, created_at) VALUES (?, 'bounced', 't')",
    )
    .run(await addressHash(" Person@Example.com "));

  const blocked = await subscribe({ send_time: "10:00" });
  assert.equal(blocked.status, 409);
  assert.equal(blocked.json.error.code, "mail_suppressed");
  assert.equal(
    (await call("GET", "/mail/subscription", { token })).status,
    200,
  );
  assert.equal(
    (
      await call("PATCH", "/mail/subscription", {
        token,
        body: { status: "paused" },
      })
    ).status,
    200,
  );
  assert.equal(
    (
      await call("PATCH", "/mail/subscription", {
        token,
        body: { status: "active" },
      })
    ).json.error.code,
    "mail_suppressed",
  );
  assert.equal(
    (await call("DELETE", "/mail/subscription", { token })).status,
    204,
  );
});

// --- 수신 거부 링크 ---

async function unsubscribeLink(sqlite: ReturnType<typeof setup>["sqlite"]) {
  const id = subscriptionId(sqlite);
  return `${BASE}/mail/unsubscribe?s=${id}&t=${await signUnsubscribe(SECRET, id)}`;
}

const statusOf = (sqlite: ReturnType<typeof setup>["sqlite"]) =>
  sqlite
    .prepare("SELECT status, ended_reason FROM mail_subscriptions")
    .get() as Json;

test("링크를 열기만 해서는 끊지 않고(보안 검사기의 미리 열기), POST로 끊는다", async () => {
  const { subscribe, sqlite, publicCall } = await world();
  await subscribe();
  const link = await unsubscribeLink(sqlite);

  const opened = await publicCall(new Request(link));
  assert.equal(opened.status, 200);
  assert.match(await opened.text(), /<form method="post"/);
  assert.equal(statusOf(sqlite).status, "active");
  assert.match(
    opened.headers.get("Content-Security-Policy") ?? "",
    /default-src 'none'/,
  );

  const done = await publicCall(new Request(link, { method: "POST" }));
  assert.equal(done.status, 200);
  assert.deepEqual(
    { ...statusOf(sqlite) },
    { status: "ended", ended_reason: "unsubscribed" },
  );

  // 여러 번 눌러도 같다
  assert.equal(
    (await publicCall(new Request(link, { method: "POST" }))).status,
    200,
  );
});

test("메일 앱의 원클릭 수신 거부(RFC 8058)도 끊는다", async () => {
  const { subscribe, sqlite, publicCall } = await world();
  await subscribe();
  const response = await publicCall(
    new Request(await unsubscribeLink(sqlite), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "List-Unsubscribe=One-Click",
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(statusOf(sqlite).status, "ended");
});

test("서명이 틀리거나 다른 구독의 서명이면 400이고 바꾸지 않는다. 비밀이 없으면 503이다", async () => {
  const { subscribe, sqlite, publicCall } = await world();
  await subscribe();
  const id = subscriptionId(sqlite);
  const forged = [
    `${BASE}/mail/unsubscribe?s=${id}&t=${"A".repeat(43)}`,
    `${BASE}/mail/unsubscribe?s=${id}&t=${await signUnsubscribe("other-secret", id)}`,
    `${BASE}/mail/unsubscribe?s=${uuid()}&t=${await signUnsubscribe(SECRET, id)}`,
    `${BASE}/mail/unsubscribe?s=${id}`,
    `${BASE}/mail/unsubscribe?s=not-a-uuid&t=x`,
  ];
  for (const link of forged) {
    const response = await publicCall(new Request(link, { method: "POST" }));
    assert.equal(response.status, 400, link);
  }
  assert.equal(statusOf(sqlite).status, "active");

  const unconfigured = await publicCall(
    new Request(await unsubscribeLink(sqlite), { method: "POST" }),
    { MAIL_LINK_SECRET: undefined },
  );
  assert.equal(unconfigured.status, 503);
  assert.equal(
    (
      await publicCall(
        new Request(`${BASE}/mail/unsubscribe`, { method: "PUT" }),
      )
    ).status,
    405,
  );
});

// --- 반송·신고 웹훅 ---

async function signed(
  body: string,
  at = Math.floor(Date.now() / 1000),
  id = "msg_1",
) {
  const key = await crypto.subtle.importKey(
    "raw",
    WEBHOOK_KEY,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(
    await crypto.subtle.sign(
      "HMAC",
      key,
      new TextEncoder().encode(`${id}.${at}.${body}`),
    ),
  );
  return new Request(`${BASE}/mail/webhooks/resend`, {
    method: "POST",
    headers: {
      "svix-id": id,
      "svix-timestamp": String(at),
      "svix-signature": `v1,${btoa(String.fromCharCode(...signature))}`,
      "Content-Type": "application/json",
    },
    body,
  });
}

const event = (type: string, data: Json) =>
  JSON.stringify({ type, created_at: "t", data });

test("영구 반송과 스팸 신고는 그 주소를 막고 그 사용자의 구독을 끝낸다(주소 원문은 남기지 않는다)", async () => {
  const { subscribe, sqlite, publicCall } = await world();
  await subscribe();

  const response = await publicCall(
    await signed(
      event("email.bounced", {
        to: ["Person <PERSON@example.com>"],
        bounce: { type: "Permanent", subType: "General" },
      }),
    ),
  );

  assert.equal(response.status, 200);
  assert.deepEqual(
    { ...statusOf(sqlite) },
    { status: "ended", ended_reason: "suppressed" },
  );
  const rows = sqlite
    .prepare("SELECT * FROM mail_suppressions")
    .all() as Json[];
  assert.equal(rows.length, 1);
  assert.equal(rows[0].address_hash, await addressHash("person@example.com"));
  assert.ok(!JSON.stringify(rows).includes("example.com"));

  await publicCall(
    await signed(event("email.complained", { to: ["x@example.org"] })),
  );
  assert.equal(
    (
      sqlite
        .prepare("SELECT reason FROM mail_suppressions WHERE address_hash = ?")
        .get(await addressHash("x@example.org")) as Json
    ).reason,
    "complained",
  );
});

test("일시적 반송과 다른 이벤트는 막지 않고 200으로 받는다", async () => {
  const { subscribe, sqlite, publicCall } = await world();
  await subscribe();
  for (const body of [
    event("email.bounced", {
      to: ["person@example.com"],
      bounce: { type: "Transient" },
    }),
    event("email.delivered", { to: ["person@example.com"] }),
  ]) {
    assert.equal((await publicCall(await signed(body))).status, 200);
  }
  assert.equal(statusOf(sqlite).status, "active");
  assert.equal(
    (
      sqlite
        .prepare("SELECT COUNT(*) AS n FROM mail_suppressions")
        .get() as Json
    ).n,
    0,
  );
});

test("서명이 없거나 틀리거나 오래된 웹훅은 401이고, 비밀이 없으면 503이다", async () => {
  const { sqlite, publicCall } = await world();
  const body = event("email.complained", { to: ["a@example.com"] });

  const tampered = await signed(body);
  const forged = new Request(tampered.url, {
    method: "POST",
    headers: tampered.headers,
    body: event("email.complained", { to: ["victim@example.com"] }),
  });
  const cases = [
    forged,
    await signed(body, Math.floor(Date.now() / 1000) - 10 * 60),
    new Request(`${BASE}/mail/webhooks/resend`, { method: "POST", body }),
  ];
  for (const request of cases) {
    assert.equal((await publicCall(request)).status, 401);
  }
  assert.equal(
    (await publicCall(await signed(body), { RESEND_WEBHOOK_SECRET: undefined }))
      .status,
    503,
  );
  assert.equal(
    (
      sqlite
        .prepare("SELECT COUNT(*) AS n FROM mail_suppressions")
        .get() as Json
    ).n,
    0,
  );
});

// --- 계정 삭제·저장 칸 ---

test("계정을 지우면 구독은 지워지고, 확인 기록과 막힌 주소는 남는다", async () => {
  const { subscribe, call, token, sqlite } = await world();
  await subscribe();
  sqlite
    .prepare(
      "INSERT INTO mail_suppressions (address_hash, reason, created_at) VALUES (?, 'complained', 't')",
    )
    .run(await addressHash("person@example.com"));

  await call("DELETE", "/account", { token });

  const count = (table: string) =>
    (sqlite.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get() as Json).n;
  assert.equal(count("mail_subscriptions"), 0);
  assert.equal(count("mail_welcomes"), 1);
  assert.equal(count("mail_suppressions"), 1);
});

test("구독·확인 기록·막힌 주소 테이블에는 주소·이름을 담는 칸이 없다", () => {
  const { sqlite } = setup();
  const columns = (table: string) =>
    (sqlite.prepare(`PRAGMA table_info(${table})`).all() as Json[]).map(
      (row) => row.name,
    );
  assert.deepEqual(columns("mail_subscriptions"), [
    "id",
    "user_id",
    "goal_id",
    "frequency",
    "weekday",
    "day_of_month",
    "send_time",
    "timezone",
    "status",
    "ended_reason",
    "created_at",
    "updated_at",
  ]);
  assert.deepEqual(columns("mail_welcomes"), ["user_key", "welcomed_at"]);
  assert.deepEqual(columns("mail_suppressions"), [
    "address_hash",
    "reason",
    "created_at",
  ]);
});

test("발송 기록은 확인 메일(welcome)도 받는다", () => {
  const { sqlite } = setup();
  sqlite
    .prepare(
      "INSERT INTO mail_sends (user_key, kind, sent_on, token, created_at) VALUES (?, 'welcome', '2026-11-06', 'tok', 't')",
    )
    .run("a".repeat(64));
  assert.throws(() =>
    sqlite
      .prepare(
        "INSERT INTO mail_sends (user_key, kind, sent_on, token, created_at) VALUES (?, 'spam', '2026-11-06', 'tok2', 't')",
      )
      .run("a".repeat(64)),
  );
});

// --- 확인과 저장 사이에 바뀌는 경우(한 문장 안에서 다시 본다) ---

/** 처음 하는 목표 확인(SELECT end_date)만 "살아 있다"로 속이는 DB — 확인 뒤에 목표가 지워진(또는 기간이 줄어든) 상황을 만든다. */
function staleGoalCheck(db: never) {
  const real = db as unknown as import("../src/db.ts").Db;
  let stubbed = false;
  return {
    ...real,
    batch: real.batch.bind(real),
    prepare(sql: string) {
      if (!stubbed && sql.startsWith("SELECT end_date FROM goals")) {
        stubbed = true;
        const stub = {
          bind: () => stub,
          first: async () => ({ end_date: null }),
          run: async () => ({ meta: { changes: 0 } }),
          all: async () => ({ results: [] }),
        };
        return stub;
      }
      return real.prepare(sql);
    },
  } as import("../src/db.ts").Db;
}

test("확인 뒤에 목표가 지워졌으면 저장하지 않고 404이다", async () => {
  const { call, token, goal, db, sqlite } = await world();
  await call("DELETE", `/goals/${goal}`, { token });
  const user = sqlite
    .prepare("SELECT id, email, google_sub FROM users")
    .get() as Json;

  const result = await putSubscription(
    staleGoalCheck(db as never),
    { id: user.id, email: user.email, googleSub: user.google_sub },
    {
      goalId: goal,
      frequency: "weekly",
      weekday: 0,
      dayOfMonth: null,
      sendTime: "09:00",
      timezone: "UTC",
      replace: false,
    },
    new Date(),
  );

  assert.equal(result.ok, false);
  assert.equal(!result.ok && result.code, "goal_not_found");
  assert.equal(
    (
      sqlite
        .prepare("SELECT COUNT(*) AS n FROM mail_subscriptions")
        .get() as Json
    ).n,
    0,
  );
});

test("가드 뒤에 주소가 막혔으면 신청·다시 켜기가 쓰지 않고 mail_suppressed이다", async () => {
  const { subscribe, call, token, goal, db, sqlite } = await world();
  await subscribe();
  await call("PATCH", "/mail/subscription", {
    token,
    body: { status: "paused" },
  });
  const user = sqlite
    .prepare("SELECT id, email, google_sub FROM users")
    .get() as Json;
  const mailUser = {
    id: user.id,
    email: user.email,
    googleSub: user.google_sub,
  };
  // 가드를 통과한 뒤 반송 웹훅이 처리된 상황
  sqlite
    .prepare(
      "INSERT INTO mail_suppressions (address_hash, reason, created_at) VALUES (?, 'bounced', 't')",
    )
    .run(await addressHash(user.email));

  const resumed = await setSubscriptionStatus(
    db as never,
    mailUser,
    "active",
    new Date(),
  );
  assert.equal(!resumed.ok && resumed.code, "mail_suppressed");
  const put = await putSubscription(
    db as never,
    mailUser,
    {
      goalId: goal,
      frequency: "weekly",
      weekday: 1,
      dayOfMonth: null,
      sendTime: "10:00",
      timezone: "UTC",
      replace: false,
    },
    new Date(),
  );
  assert.equal(!put.ok && put.code, "mail_suppressed");
  assert.equal(statusOf(sqlite).status, "paused");
});

test("웹훅 본문이 64KiB를 넘으면 서명을 보기 전에 413이다(선언된 길이도, 흘려 보낸 본문도)", async () => {
  const { publicCall } = await world();
  const big = "x".repeat(64 * 1024 + 1);

  const declared = await publicCall(
    new Request(`${BASE}/mail/webhooks/resend`, { method: "POST", body: big }),
  );
  assert.equal(declared.status, 413);

  const stream = new ReadableStream({
    start(controller) {
      for (let i = 0; i < 70; i++) {
        controller.enqueue(new TextEncoder().encode("y".repeat(1024)));
      }
      controller.close();
    },
  });
  const streamed = await publicCall(
    new Request(`${BASE}/mail/webhooks/resend`, {
      method: "POST",
      body: stream,
      duplex: "half",
    } as RequestInit),
  );
  assert.equal(streamed.status, 413);
});

test("확인 뒤에 다른 기기가 기간을 줄여 목표가 끝났으면 저장하지 않고 goal_ended이다", async () => {
  const { goal, db, sqlite } = await world();
  sqlite
    .prepare(
      "UPDATE goals SET start_date = '2026-01-01', end_date = '2026-01-31' WHERE id = ?",
    )
    .run(goal);
  const user = sqlite
    .prepare("SELECT id, email, google_sub FROM users")
    .get() as Json;

  const result = await putSubscription(
    staleGoalCheck(db as never),
    { id: user.id, email: user.email, googleSub: user.google_sub },
    {
      goalId: goal,
      frequency: "weekly",
      weekday: 0,
      dayOfMonth: null,
      sendTime: "09:00",
      timezone: "UTC",
      replace: false,
    },
    new Date("2026-11-06T03:00:00.000Z"),
  );

  assert.equal(!result.ok && result.code, "goal_ended");
  assert.equal(
    (
      sqlite
        .prepare("SELECT COUNT(*) AS n FROM mail_subscriptions")
        .get() as Json
    ).n,
    0,
  );
});

test("JSON 본문도 길이를 알리지 않으면 읽으면서 한도에서 멈춘다(413)", async () => {
  const { readJson } = await import("../src/http.ts");
  const stream = new ReadableStream({
    start(controller) {
      for (let i = 0; i < 4; i++) {
        controller.enqueue(new TextEncoder().encode("z".repeat(512)));
      }
      controller.close();
    },
  });
  const read = await readJson(
    new Request("https://server.example/x", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: stream,
      duplex: "half",
    } as RequestInit),
    1024,
  );
  assert.equal(read.ok, false);
  assert.equal(!read.ok && read.response.status, 413);
});

test("막힌 주소의 구독은 웹훅 주소와 대소문자가 같으면(비ASCII 포함) 끝난다", async () => {
  const fixture = setup();
  const token = await fixture.signIn("sub-9", "Ärger@example.com");
  const goal = uuid();
  await fixture.call("PUT", `/goals/${goal}`, { token, body: GOAL });
  await fixture.call("PUT", "/mail/subscription", {
    token,
    body: { goal_id: goal, ...SCHEDULE },
  });
  const { suppress } = await import("../src/mail/suppression.ts");

  await suppress(
    fixture.db as never,
    "Ärger@example.com",
    "bounced",
    new Date(),
  );

  assert.equal(
    (
      fixture.sqlite
        .prepare("SELECT status FROM mail_subscriptions")
        .get() as Json
    ).status,
    "ended",
  );
});
