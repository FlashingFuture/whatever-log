import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { type Env, runReports } from "../src/index.ts";
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

test("일시적 실패는 다음 실행이 같은 멱등 키로 다시 보내고, 하루 한도에서 멈춘다", async () => {
  const { run, port } = await world();
  port.results = [
    { ok: false, reason: "unavailable", retryable: true },
    { ok: false, reason: "unavailable", retryable: true },
  ];
  assert.equal((await run(MONDAY)).retry, 1);
  assert.equal((await run("2026-11-09T00:15:00.000Z")).retry, 1);
  // 접수됐을 수 있는 실패 두 번으로 이 사용자의 하루 보고서 한도(2)를 썼다 — 같은 날 더 보내지 않는다
  assert.equal((await run("2026-11-09T00:25:00.000Z")).limited, 1);
  assert.equal(port.sent.length, 2);
  assert.equal(port.sent[0].idempotencyKey, port.sent[1].idempotencyKey);
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
      if (sql.startsWith("SELECT 1 AS present FROM mail_reports")) {
        sqlite
          .prepare(
            "INSERT OR IGNORE INTO mail_reports (subscription_id, period_key, status, created_at, updated_at) VALUES (?, '2026-11-09', 'sending', 't', 't')",
          )
          .run(id);
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
