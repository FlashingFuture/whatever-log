import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { type Env, runReports } from "../src/index.ts";
import { LIMITS } from "../src/mail/config.ts";
import { dispatchReports } from "../src/mail/dispatch.ts";
import type { MailMessage, SendResult } from "../src/mail/port.ts";
import { formatMinutes } from "../src/mail/report.ts";
import { addressHash } from "../src/mail/suppression.ts";
import { GOAL, type Json, setup, uuid } from "./helpers/syncFixtures.ts";

class FakeMail {
  sent: MailMessage[] = [];
  results: SendResult[] = [];
  async send(message: MailMessage): Promise<SendResult> {
    this.sent.push(message);
    return this.results.shift() ?? { ok: true, id: `msg-${this.sent.length}` };
  }
}

const LINKS = { secret: "s", baseUrl: "https://server.example" };

/**
 * 금요일(2026-11-06, 서울 12:00)에 목표(평일, 하루 120분)를 만들고 매주 월요일 09:00(서울) 보고서를 신청한 사용자.
 * 첫 보고서는 2026-11-09(월) 09:00 서울 = 00:00 UTC, 구간은 11-02 ~ 11-08이다(목표를 만든 금요일 하루만 목표량이 있다).
 */
async function world(schedule: Json = {}, goalBody: Json = {}) {
  const fixture = setup();
  const port = new FakeMail();
  const mail = {
    port,
    sender: {
      from: "whatever.log <reports@example.com>",
      mode: "domain" as const,
    },
    links: LINKS,
  };
  fixture.deps.mail = () => mail;
  const token = await fixture.signIn("sub-1", "person@example.com");
  const goal = uuid();
  await fixture.call("PUT", `/goals/${goal}`, {
    token,
    body: { ...GOAL, ...goalBody },
  });
  const subscribed = await fixture.call("PUT", "/mail/subscription", {
    token,
    body: {
      goal_id: goal,
      frequency: "weekly",
      weekday: 0,
      send_time: "09:00",
      timezone: "Asia/Seoul",
      ...schedule,
    },
  });
  assert.equal(subscribed.status, 201, JSON.stringify(subscribed.json));
  port.sent = []; // 확인 메일은 빼고 본다
  const progress = async (
    device: string,
    day: string,
    minutes: number,
    target = 120,
  ) =>
    fixture.call("PUT", "/progress", {
      token,
      body: {
        device_id: device,
        entries: [{ goal_id: goal, day, minutes, target_minutes: target }],
      },
    });
  const run = (iso: string) =>
    dispatchReports(fixture.db as never, mail, new Date(iso));
  return { ...fixture, port, mail, token, goal, progress, run };
}

const MONDAY = "2026-11-09T00:05:00.000Z"; // 서울 월 09:05

test("보낼 시각이 되면 지난주 보고서를 한 통 보내고, 다시 돌아도 같은 구간은 보내지 않는다", async () => {
  const { run, port, sqlite } = await world();

  assert.equal((await run("2026-11-08T23:50:00.000Z")).sent, 0); // 서울 월 08:50
  const first = await run(MONDAY);
  assert.equal(first.sent, 1);
  assert.equal((await run("2026-11-09T00:15:00.000Z")).sent, 0);

  assert.equal(port.sent.length, 1);
  const [message] = port.sent;
  const id = (sqlite.prepare("SELECT id FROM mail_subscriptions").get() as Json)
    .id;
  assert.equal(message.to, "person@example.com");
  assert.equal(message.idempotencyKey, `report-${id}-2026-11-09`);
  assert.match(message.subject, /공부 주간 보고서 · 11월 2일 ~ 11월 8일/);
  assert.ok(
    message.headers?.["List-Unsubscribe"]?.includes("/mail/unsubscribe?s="),
  );
  assert.equal(
    (sqlite.prepare("SELECT status FROM mail_reports").get() as Json).status,
    "sent",
  );
});

test("신청하기 전의 발송 시각은 건너뛴다(신청하자마자 지난 보고서가 가지 않게)", async () => {
  const { run, port } = await world({ weekday: 4 }); // 금요일 09:00 — 신청한 금요일 12:00보다 이르다
  assert.equal((await run("2026-11-06T04:00:00.000Z")).sent, 0);
  assert.equal((await run("2026-11-13T00:05:00.000Z")).sent, 1); // 다음 금요일
  assert.equal(port.sent.length, 1);
});

test("달성은 모든 기기의 합, 목표량은 목표를 적용하는 날만(기록이 없는 날은 서버가 아는 목표로)", async () => {
  const { run, port, progress } = await world();
  await progress(uuid(), "2026-11-06", 60); // 금(목표 만든 날) 기기 A
  const b = uuid();
  await progress(b, "2026-11-06", 30); // 금 기기 B
  await progress(b, "2026-11-07", 20); // 토(쉬는 날) — 달성에는 들어가고 목표량은 없다
  await progress(b, "2026-11-05", 45); // 목, 목표를 만들기 전 — 목표량은 없다

  await run(MONDAY);

  const text = port.sent[0].text;
  // 목표량: 금 120분만 / 달성: 60+30+20+45 = 155분
  assert.match(
    text,
    new RegExp(
      `목표 ${formatMinutes(120)} 중 ${formatMinutes(155)} \\(129%\\)`,
    ),
  );
  assert.match(text, /11월 6일 \(금\) 1시간 30분 \/ 2시간/);
  assert.match(text, /11월 7일 \(토\) 20분 \(목표 없는 날\)/);
  assert.match(text, /마지막 동기화 2026-11-06/);
  assert.ok(!text.includes("Code.exe"));
});

test("목표를 적용하는 날이 없는 구간은 그렇게 알린다", async () => {
  const { run, port } = await world({}, { weekdays: [5, 6] }); // 주말 목표를 금요일에 만들었다 → 11-07·08만
  await run(MONDAY);
  assert.match(port.sent[0].text, /목표 4시간 중 0분 \(0%\)/);
});

test("매일 보고서는 날짜별 목록 없이 전날 하루만", async () => {
  const { run, port, progress } = await world({
    frequency: "daily",
    weekday: null,
  });
  await progress(uuid(), "2026-11-08", 30);
  const result = await run(MONDAY);
  assert.equal(result.sent, 1);
  assert.match(port.sent[0].subject, /일간 보고서 · 11월 8일/);
});

test("목표 기간이 구간을 덮으면 마지막 보고서를 보내고 구독을 끝낸다", async () => {
  const { run, port, sqlite } = await world(
    {},
    { start_date: "2026-11-06", end_date: "2026-11-07" },
  );
  await run(MONDAY);
  assert.equal(port.sent.length, 1);
  assert.match(port.sent[0].text, /마지막 보고서/);
  assert.deepEqual(
    {
      ...(sqlite
        .prepare("SELECT status, ended_reason FROM mail_subscriptions")
        .get() as Json),
    },
    { status: "ended", ended_reason: "goal_ended" },
  );
  assert.equal((await run("2026-11-16T00:05:00.000Z")).sent, 0);
});

test("구간이 목표 종료일보다 뒤면 보내지 않고 끝낸다", async () => {
  const { run, port, sqlite } = await world();
  sqlite
    .prepare(
      "UPDATE goals SET start_date = '2026-11-06', end_date = '2026-11-06'",
    )
    .run();
  await run(MONDAY); // 11-02 ~ 11-08 구간은 종료일(11-06)을 덮는다 → 마지막 보고서
  assert.equal(port.sent.length, 1);

  sqlite
    .prepare(
      "UPDATE mail_subscriptions SET status = 'active', ended_reason = NULL",
    )
    .run();
  await run("2026-11-16T00:05:00.000Z"); // 11-09 ~ 11-15는 종료일 뒤
  assert.equal(port.sent.length, 1);
  assert.equal(
    (
      sqlite
        .prepare("SELECT ended_reason FROM mail_subscriptions")
        .get() as Json
    ).ended_reason,
    "goal_ended",
  );
});

test("막힌 주소면 보내지 않고 구독을 끝낸다", async () => {
  const { run, port, sqlite } = await world();
  sqlite
    .prepare(
      "INSERT INTO mail_suppressions (address_hash, reason, created_at) VALUES (?, 'bounced', 't')",
    )
    .run(await addressHash("person@example.com"));
  await run(MONDAY);
  assert.equal(port.sent.length, 0);
  assert.equal(
    (
      sqlite
        .prepare("SELECT ended_reason FROM mail_subscriptions")
        .get() as Json
    ).ended_reason,
    "suppressed",
  );
});

test("꺼진 구독·끝난 구독·지운 목표에는 보내지 않는다", async () => {
  const paused = await world();
  await paused.call("PATCH", "/mail/subscription", {
    token: paused.token,
    body: { status: "paused" },
  });
  assert.equal((await paused.run(MONDAY)).sent, 0);

  const deleted = await world();
  await deleted.call("DELETE", `/goals/${deleted.goal}`, {
    token: deleted.token,
  });
  assert.equal((await deleted.run(MONDAY)).sent, 0);
});

test("링크 설정이 없으면 보내지 않고 자리도 잡지 않는다", async () => {
  const { db, sqlite, port } = await world();
  const summary = await dispatchReports(
    db as never,
    { port, sender: { from: "x <r@example.com>", mode: "domain" } },
    new Date(MONDAY),
  );
  assert.equal(summary.notConfigured, true);
  assert.equal(port.sent.length, 0);
  assert.equal(
    (sqlite.prepare("SELECT COUNT(*) AS n FROM mail_reports").get() as Json).n,
    0,
  );
});

test("거절된 구간은 failed로 두고 다시 보내지 않는다", async () => {
  const { run, port, sqlite } = await world();
  port.results = [{ ok: false, reason: "rejected", retryable: false }];
  assert.equal((await run(MONDAY)).failed, 1);
  assert.equal((await run("2026-11-09T00:15:00.000Z")).sent, 0);
  assert.equal(port.sent.length, 1);
  assert.equal(
    (sqlite.prepare("SELECT status FROM mail_reports").get() as Json).status,
    "failed",
  );
});

test("서비스 한도(rate_limited)는 발송 한도의 자리를 돌려주고 다음 실행에 보낸다", async () => {
  const { run, port } = await world();
  port.results = [{ ok: false, reason: "rate_limited", retryable: true }];
  await run(MONDAY);
  await run("2026-11-09T00:15:00.000Z");
  await run("2026-11-09T00:25:00.000Z");
  assert.equal(port.sent.length, 2); // 실패 한 번 + 성공 한 번(한도에 막히지 않았다)
});

test("다른 실행이 먼저 자리를 잡은 구간은 보내지 않는다(Cron이 겹쳐도 한 번)", async () => {
  const { run, port, sqlite } = await world();
  const id = (sqlite.prepare("SELECT id FROM mail_subscriptions").get() as Json)
    .id;
  sqlite
    .prepare(
      "INSERT INTO mail_reports (subscription_id, period_key, status, created_at, updated_at) VALUES (?, '2026-11-09', 'sending', ?, ?)",
    )
    .run(id, MONDAY, MONDAY);
  assert.equal((await run(MONDAY)).sent, 0);
  assert.equal(port.sent.length, 0);
});

test("발송 기록에는 주소·제목·본문을 담는 칸이 없다", () => {
  const { sqlite } = setup();
  const columns = (
    sqlite.prepare("PRAGMA table_info(mail_reports)").all() as Json[]
  ).map((row) => row.name);
  assert.deepEqual(columns, [
    "subscription_id",
    "period_key",
    "status",
    "provider_id",
    "send_token",
    "created_at",
    "updated_at",
  ]);
});

test("Cron 진입점: 메일 설정이 없으면 보내지 않고 멈추지 않는다", async () => {
  const { db } = await world();
  const env: Env = {
    GOOGLE_CLIENT_ID: "c",
    GOOGLE_CLIENT_SECRET: "s",
    DB: db as never,
  };
  await runReports(env, new Date(MONDAY)); // RESEND_API_KEY 없음 → 설정 오류를 로그에만
  const waited: Promise<unknown>[] = [];
  await worker.scheduled({} as never, env, {
    waitUntil: (promise: Promise<unknown>) => waited.push(promise),
  } as never);
  await Promise.all(waited);
});

test("확인과 자리 잡기 사이에 다른 실행이 끼어도 자리를 잡은 쪽만 보낸다", async () => {
  const { db, sqlite, mail, port } = await world();
  const id = (sqlite.prepare("SELECT id FROM mail_subscriptions").get() as Json)
    .id;
  const real = db as unknown as import("../src/db.ts").Db;
  // "이미 보냈나" 확인은 아무것도 못 봤는데, 그 직후 다른 실행이 자리를 잡은 상황
  const racing = {
    batch: real.batch.bind(real),
    prepare(sql: string) {
      if (
        sql.startsWith(
          "SELECT subscription_id, period_key, status, created_at, updated_at FROM mail_reports",
        )
      ) {
        sqlite
          .prepare(
            "INSERT OR IGNORE INTO mail_reports (subscription_id, period_key, status, created_at, updated_at) VALUES (?, '2026-11-09', 'sending', ?, ?)",
          )
          .run(id, MONDAY, MONDAY);
        const stub = {
          bind: () => stub,
          first: async () => null,
          run: async () => ({ meta: { changes: 0 } }),
          all: async () => ({ results: [] }),
        };
        return stub;
      }
      return real.prepare(sql);
    },
  } as import("../src/db.ts").Db;

  const summary = await dispatchReports(racing, mail, new Date(MONDAY));

  assert.equal(summary.sent, 0);
  assert.equal(port.sent.length, 0);
});

// --- 쿼리 예산, 예외, 남은 자리 ---

/** 같은 시각(월 09:00 서울)에 매주 보고서를 받는 사용자 n명을 더한다. */
async function addSubscribers(
  fixture: Awaited<ReturnType<typeof world>>,
  n: number,
) {
  for (let i = 0; i < n; i++) {
    const token = await fixture.signIn(`extra-${i}`, `extra${i}@example.com`);
    const goal = uuid();
    await fixture.call("PUT", `/goals/${goal}`, { token, body: GOAL });
    await fixture.call("PUT", "/mail/subscription", {
      token,
      body: {
        goal_id: goal,
        frequency: "weekly",
        weekday: 0,
        send_time: "09:00",
        timezone: "Asia/Seoul",
      },
    });
  }
  fixture.port.sent = [];
}

test("한 실행은 쿼리 예산 안에서만 보내고 남은 것은 다음 실행이 보낸다(모두 한 번씩)", async () => {
  const fixture = await world();
  await addSubscribers(fixture, 11); // 모두 12명
  const counts: number[] = [];
  let total = 0;
  for (const minute of ["05", "15", "25", "35"]) {
    const summary = await fixture.run(`2026-11-09T00:${minute}:00.000Z`);
    assert.ok(
      summary.queries <= LIMITS.queriesPerRun,
      `queries ${summary.queries}`,
    );
    counts.push(summary.sent);
    total += summary.sent;
  }
  assert.ok(counts[0] > 0 && counts[0] < 12, `첫 실행 ${counts[0]}통`);
  assert.equal(total, 12);
  assert.equal(new Set(fixture.port.sent.map((m) => m.to)).size, 12);
});

test("보낼 것이 없으면 구독이 많아도 쿼리는 몇 번뿐이다", async () => {
  const fixture = await world();
  await addSubscribers(fixture, 40);
  // 41명을 모두 보낼 때까지 10분마다 돈다(한 실행에 다섯 통 안팎)
  let at = Date.parse(MONDAY);
  for (
    let i = 0;
    i < 20 && fixture.port.sent.length < 41;
    i++, at += 10 * 60 * 1000
  ) {
    await fixture.run(new Date(at).toISOString());
  }
  assert.equal(fixture.port.sent.length, 41);

  const idle = await fixture.run(new Date(at + 10 * 60 * 1000).toISOString());
  assert.equal(idle.sent, 0);
  assert.ok(idle.queries <= 3, `queries ${idle.queries}`);
});

test("자리를 잡은 뒤 예외가 나면 자리를 풀고 다음 구독으로 가며, 다음 실행이 같은 멱등 키로 다시 보낸다", async () => {
  const fixture = await world();
  await addSubscribers(fixture, 1);
  let calls = 0;
  const attempts: MailMessage[] = [];
  const original = fixture.port.send.bind(fixture.port);
  fixture.port.send = async (message) => {
    calls += 1;
    attempts.push(message);
    if (calls === 1) throw new Error("boom"); // 요청을 보낸 뒤의 예외 — 접수됐을 수 있다
    return original(message);
  };

  const first = await fixture.run(MONDAY);
  assert.equal(first.retry, 1);
  assert.equal(first.sent, 1); // 다른 구독은 같은 실행에서 보냈다
  const second = await fixture.run("2026-11-09T00:15:00.000Z");
  assert.equal(second.sent, 1);
  // 다시 보낸 것은 예외가 난 첫 요청과 같은 수신자·같은 멱등 키다
  const retried = attempts[2];
  assert.equal(retried.to, attempts[0].to);
  assert.equal(retried.idempotencyKey, attempts[0].idempotencyKey);
  assert.equal(
    (
      fixture.sqlite
        .prepare("SELECT COUNT(*) AS n FROM mail_reports WHERE status = 'sent'")
        .get() as Json
    ).n,
    2,
  );
});

test("구독 하나의 값이 이상해도(시간대) 그 구독만 건너뛰고 나머지는 보낸다", async () => {
  const fixture = await world();
  await addSubscribers(fixture, 1);
  fixture.sqlite
    .prepare(
      "UPDATE mail_subscriptions SET timezone = 'Mars/Olympus' WHERE user_id = (SELECT MIN(id) FROM users)",
    )
    .run();
  const summary = await fixture.run(MONDAY);
  assert.equal(summary.sent, 1);
});

test("도중에 죽은 실행이 남긴 자리(30분 넘은 sending)는 다시 잡아 보낸다", async () => {
  const { run, port, sqlite } = await world();
  const id = (sqlite.prepare("SELECT id FROM mail_subscriptions").get() as Json)
    .id;
  sqlite
    .prepare(
      "INSERT INTO mail_reports (subscription_id, period_key, status, created_at, updated_at) VALUES (?, '2026-11-09', 'sending', ?, ?)",
    )
    .run(id, MONDAY, MONDAY);

  assert.equal((await run("2026-11-09T00:20:00.000Z")).sent, 0); // 15분 — 아직 다른 실행이 보내는 중일 수 있다
  assert.equal((await run("2026-11-09T00:40:00.000Z")).sent, 1); // 35분 — 다시 잡는다
  assert.equal(port.sent.length, 1);
});

// --- 결과를 모르는 발송, 멱등 키의 유효 기간, 요청 전 실패 ---

const reportRow = (sqlite: ReturnType<typeof setup>["sqlite"]) =>
  sqlite.prepare("SELECT status, provider_id FROM mail_reports").get() as Json;

test("결과를 모르는 발송은 unknown으로 두고, 멱등 키가 살아 있는 동안(23시간)만 같은 키로 다시 보낸다", async () => {
  const { run, port, sqlite } = await world();
  port.results = [{ ok: false, reason: "unavailable", retryable: true }];

  assert.equal((await run(MONDAY)).retry, 1);
  assert.equal(reportRow(sqlite).status, "unknown");
  // 다음 날 01:00 UTC(첫 시도 25시간 뒤) — 하루 한도도 새로 열렸지만 멱등 키가 지났을 수 있어 다시 보내지 않는다
  const late = await run("2026-11-10T01:05:00.000Z");
  assert.equal(late.sent + late.retry, 0);
  assert.equal(port.sent.length, 1);
});

test("멱등 키 기간 안이면 다시 보내고, 같은 키로 다른 내용(409)이면 이미 접수된 것으로 보고 sent로 둔다", async () => {
  const { run, port, sqlite, progress } = await world();
  port.results = [
    { ok: false, reason: "unavailable", retryable: true },
    {
      ok: false,
      reason: "rejected",
      retryable: false,
      detail: "invalid_idempotent_request",
    },
  ];
  await run(MONDAY);
  await progress(uuid(), "2026-11-06", 15); // 그사이 진행 기록이 바뀌어 본문이 달라졌다
  const second = await run("2026-11-09T00:15:00.000Z");

  assert.equal(second.sent, 1);
  assert.equal(second.failed, 0);
  assert.equal(reportRow(sqlite).status, "sent");
  assert.equal(port.sent[0].idempotencyKey, port.sent[1].idempotencyKey);
  assert.equal((await run("2026-11-09T00:25:00.000Z")).sent, 0);
});

test("접수 번호 없는 2xx(no_id)는 접수된 것으로 보고 다시 보내지 않는다", async () => {
  const { run, port, sqlite } = await world();
  port.results = [
    { ok: false, reason: "unavailable", retryable: false, detail: "no_id" },
  ];
  assert.equal((await run(MONDAY)).sent, 1);
  assert.deepEqual(
    { ...reportRow(sqlite) },
    { status: "sent", provider_id: null },
  );
  assert.equal((await run("2026-11-09T00:15:00.000Z")).sent, 0);
  assert.equal(port.sent.length, 1);
});

test("메일 요청 전에 실패하면 자리와 발송 한도를 모두 돌려준다", async () => {
  const { db, mail, sqlite, port } = await world();
  const real = db as unknown as import("../src/db.ts").Db;
  let broken = true;
  const failing = {
    batch: real.batch.bind(real),
    prepare(sql: string) {
      if (broken && sql.startsWith("SELECT p.day AS day")) {
        broken = false;
        throw new Error("d1 down");
      }
      return real.prepare(sql);
    },
  } as import("../src/db.ts").Db;

  assert.equal(
    (await dispatchReports(failing, mail, new Date(MONDAY))).retry,
    1,
  );
  const count = (table: string) =>
    (
      sqlite
        .prepare(
          `SELECT COUNT(*) AS n FROM ${table} WHERE ${table === "mail_sends" ? "kind = 'report'" : "1"}`,
        )
        .get() as Json
    ).n;
  assert.equal(count("mail_sends"), 0);
  assert.equal(count("mail_reports"), 0);
  assert.equal(port.sent.length, 0);
});

test("실행 처음에 못 본 막힌 주소도 보내기 직전에 다시 보고 막는다", async () => {
  const { db, mail, sqlite, port } = await world();
  const real = db as unknown as import("../src/db.ts").Db;
  // 실행 처음의 막힌 주소 읽기는 비어 있었고, 그 직후 웹훅이 막았다
  const late = {
    batch: real.batch.bind(real),
    prepare(sql: string) {
      if (
        sql.startsWith(
          "SELECT address_hash FROM mail_suppressions WHERE address_hash IN",
        )
      ) {
        const stub = {
          bind: () => stub,
          first: async () => null,
          run: async () => ({ meta: { changes: 0 } }),
          all: async () => ({ results: [] }),
        };
        return stub;
      }
      return real.prepare(sql);
    },
  } as import("../src/db.ts").Db;
  sqlite
    .prepare(
      "INSERT INTO mail_suppressions (address_hash, reason, created_at) VALUES (?, 'complained', 't')",
    )
    .run(await addressHash("person@example.com"));

  const summary = await dispatchReports(late, mail, new Date(MONDAY));

  assert.equal(summary.sent, 0);
  assert.equal(port.sent.length, 0);
  assert.equal(
    (
      sqlite
        .prepare("SELECT ended_reason FROM mail_subscriptions")
        .get() as Json
    ).ended_reason,
    "suppressed",
  );
});

test("보내는 사이 다른 목표로 옮긴 구독은 이전 목표의 종료 처리로 끝나지 않는다", async () => {
  const { run, port, sqlite, call, token } = await world(
    {},
    { start_date: "2026-11-06", end_date: "2026-11-07" }, // 이번 보고서가 마지막
  );
  const other = uuid();
  await call("PUT", `/goals/${other}`, {
    token,
    body: { ...GOAL, name: "운동" },
  });
  const original = port.send.bind(port);
  port.send = async (message) => {
    // 발송 응답을 기다리는 사이 사용자가 구독을 다른 목표로 옮겼다(같은 id, 새 updated_at)
    sqlite
      .prepare(
        "UPDATE mail_subscriptions SET goal_id = ?, updated_at = '2026-11-09T00:05:30.000Z'",
      )
      .run(other);
    return original(message);
  };

  await run(MONDAY);

  const row = sqlite
    .prepare("SELECT goal_id, status FROM mail_subscriptions")
    .get() as Json;
  assert.deepEqual([row.goal_id, row.status], [other, "active"]);
});

test("같은 멱등 키로 다시 보낼 때는 발송 한도를 새로 잡지 않는다(장애가 이어져도 한도가 줄지 않는다)", async () => {
  const { run, port, sqlite } = await world();
  port.results = [
    { ok: false, reason: "unavailable", retryable: true },
    { ok: false, reason: "unavailable", retryable: true },
    { ok: false, reason: "unavailable", retryable: true },
  ];
  for (const minute of ["05", "15", "25", "35"]) {
    const summary = await run(`2026-11-09T00:${minute}:00.000Z`);
    assert.equal(summary.limited, 0);
  }
  assert.equal(port.sent.length, 4); // 세 번 결과 모름 → 네 번째에 보냄
  assert.ok(
    port.sent.every((m) => m.idempotencyKey === port.sent[0].idempotencyKey),
  );
  const reports = (
    sqlite
      .prepare("SELECT COUNT(*) AS n FROM mail_sends WHERE kind = 'report'")
      .get() as Json
  ).n;
  assert.equal(reports, 1); // 첫 시도의 자리 하나
  assert.equal(
    (sqlite.prepare("SELECT status FROM mail_reports").get() as Json).status,
    "sent",
  );
});

test("다시 보내는 구간은 새 구간 뒤에 보낸다(장애 중에도 새 보고서가 먼저)", async () => {
  const fixture = await world();
  fixture.port.results = [
    { ok: false, reason: "unavailable", retryable: true },
  ];
  await fixture.run(MONDAY); // 첫 구독(person): 결과 모름 → 다음 실행에서 다시 보낼 구간
  await addSubscribers(fixture, 1); // 두 번째 구독(extra0): 같은 월요일 구간이 새로 보낼 것
  // 정렬이 없으면 신청 순(updated_at)으로 person이 먼저 가도록, extra0을 더 늦게 신청한 것으로 둔다
  fixture.sqlite
    .prepare(
      "UPDATE mail_subscriptions SET updated_at = '2026-11-06T05:00:00.000Z' WHERE user_id = (SELECT MAX(id) FROM users)",
    )
    .run();

  await fixture.run("2026-11-09T00:15:00.000Z");

  assert.deepEqual(
    fixture.port.sent.map((m) => m.to),
    ["extra0@example.com", "person@example.com"],
  );
});

test("겹친 실행이 남긴 unknown을 다시 잡았으면, 실행 처음에 못 봤어도 다시 보내는 것으로 다룬다(요청 전 실패에도 첫 시도 시각을 지킨다)", async () => {
  const { db, mail, sqlite } = await world();
  const id = (sqlite.prepare("SELECT id FROM mail_subscriptions").get() as Json)
    .id;
  // 다른 실행이 첫 시도를 하고 결과를 몰라 unknown으로 둔 구간(첫 시도 00:01)
  sqlite
    .prepare(
      "INSERT INTO mail_reports (subscription_id, period_key, status, created_at, updated_at) VALUES (?, '2026-11-09', 'unknown', '2026-11-09T00:01:00.000Z', '2026-11-09T00:01:00.000Z')",
    )
    .run(id);
  const real = db as unknown as import("../src/db.ts").Db;
  const stale = {
    batch: real.batch.bind(real),
    prepare(sql: string) {
      // 이 실행의 처음 읽기는 그 행을 보지 못했고, 보고서 계산에서 실패한다(요청 전)
      if (
        sql.startsWith(
          "SELECT subscription_id, period_key, status, created_at, updated_at FROM mail_reports",
        )
      ) {
        const stub = {
          bind: () => stub,
          first: async () => null,
          run: async () => ({ meta: { changes: 0 } }),
          all: async () => ({ results: [] }),
        };
        return stub;
      }
      if (sql.startsWith("SELECT p.day AS day")) throw new Error("d1 down");
      return real.prepare(sql);
    },
  } as import("../src/db.ts").Db;

  await dispatchReports(stale, mail, new Date("2026-11-09T00:15:00.000Z"));

  const row = sqlite
    .prepare("SELECT status, created_at FROM mail_reports")
    .get() as Json;
  assert.deepEqual(
    [row.status, row.created_at],
    ["unknown", "2026-11-09T00:01:00.000Z"],
  );
});
