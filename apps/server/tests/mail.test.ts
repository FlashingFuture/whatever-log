import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LIMITS,
  MailConfigError,
  resolveProvider,
  resolveSender,
} from "../src/mail/config.ts";
import { createMail } from "../src/mail/factory.ts";
import type { MailMessage, MailPort, SendResult } from "../src/mail/port.ts";
import { createResendMail } from "../src/mail/resend.ts";
import { maskEmail } from "../src/mail/testMail.ts";
import { deleteAccount } from "../src/sync/account.ts";
import { DAY_MS, type Json, setup } from "./helpers/syncFixtures.ts";

// --- 설정 ---

test("서비스 이름이 비어 있으면 resend이고, 모르는 이름은 설정 오류이다", () => {
  assert.equal(resolveProvider({}), "resend");
  assert.equal(resolveProvider({ MAIL_PROVIDER: " resend " }), "resend");
  assert.throws(
    () => resolveProvider({ MAIL_PROVIDER: "sendgrid" }),
    MailConfigError,
  );
});

test("도메인이 없으면 서비스의 시험용 발신 주소(샌드박스)를 쓴다", () => {
  for (const env of [
    {},
    { MAIL_FROM_DOMAIN: "" },
    { MAIL_FROM_DOMAIN: "  " },
  ]) {
    assert.deepEqual(resolveSender(env), {
      from: "whatever.log <onboarding@resend.dev>",
      mode: "sandbox",
    });
  }
});

test("도메인을 채우면 그 도메인의 발신 주소로 바뀐다(대소문자는 같게 본다)", () => {
  assert.deepEqual(resolveSender({ MAIL_FROM_DOMAIN: "example.com" }), {
    from: "whatever.log <reports@example.com>",
    mode: "domain",
  });
  assert.equal(
    resolveSender({ MAIL_FROM_DOMAIN: " Mail.Example.COM " }).from,
    "whatever.log <reports@mail.example.com>",
  );
});

test("도메인 값이 이상하면 잘못된 From으로 보내지 않고 설정 오류를 낸다", () => {
  for (const bad of [
    "https://example.com",
    "example.com/path",
    "reports@example.com",
    "exa mple.com",
    "example",
    "-bad.com",
    "example..com",
    "example.c",
    "a".repeat(64) + ".com",
  ]) {
    assert.throws(
      () => resolveSender({ MAIL_FROM_DOMAIN: bad }),
      MailConfigError,
      bad,
    );
  }
});

test("서비스를 고르는 곳은 팩토리 하나이고, 키가 없으면 설정 오류이다", () => {
  assert.throws(() => createMail({}, fetch), MailConfigError);
  assert.throws(
    () => createMail({ RESEND_API_KEY: "  " }, fetch),
    MailConfigError,
  );
  assert.ok(
    typeof createMail({ RESEND_API_KEY: "re_x" }, fetch).send === "function",
  );
});

// --- Resend 어댑터 ---

const MESSAGE: MailMessage = {
  from: "whatever.log <reports@example.com>",
  to: "person@example.com",
  subject: "제목",
  text: "본문",
  html: "<p>본문</p>",
  idempotencyKey: "k-1",
};

function fakeFetch(
  respond: (request: {
    url: string;
    init: RequestInit;
  }) => Response | Promise<Response>,
) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(input), init: init ?? {} };
    calls.push(call);
    return respond(call);
  }) as typeof fetch;
  return { fn, calls };
}

const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

test("Resend 요청은 키를 Authorization에만 담고, 수신자는 목록 하나로 보낸다", async () => {
  const { fn, calls } = fakeFetch(() => json({ id: "msg-1" }, 200));
  const result = await createResendMail({
    apiKey: "re_SECRET",
    fetch: fn,
  }).send(MESSAGE);

  assert.deepEqual(result, { ok: true, id: "msg-1" });
  const [call] = calls;
  assert.equal(call.url, "https://api.resend.com/emails");
  assert.equal(call.init.method, "POST");
  const headers = call.init.headers as Record<string, string>;
  assert.equal(headers.Authorization, "Bearer re_SECRET");
  assert.equal(headers["Idempotency-Key"], "k-1");
  const body = JSON.parse(String(call.init.body));
  assert.deepEqual(body.to, ["person@example.com"]);
  assert.equal(body.from, MESSAGE.from);
  assert.ok(!String(call.init.body).includes("re_SECRET"));
});

test("실패 응답은 우리 분류로 옮기고, 결과 어디에도 키가 담기지 않는다", async () => {
  const cases: [number, unknown, string, boolean][] = [
    [401, { name: "missing_api_key" }, "unauthorized", false],
    [403, { name: "invalid_api_key" }, "unauthorized", false],
    [
      403,
      { name: "validation_error", message: "person@example.com 은(는) ..." },
      "rejected",
      false,
    ],
    [422, { name: "invalid_from_address" }, "rejected", false],
    [429, { name: "rate_limit_exceeded" }, "rate_limited", true],
    [500, { name: "internal_server_error" }, "unavailable", true],
    [503, "not json", "unavailable", true],
  ];
  for (const [status, body, reason, retryable] of cases) {
    const { fn } = fakeFetch(() =>
      typeof body === "string"
        ? new Response(body, { status })
        : json(body, status),
    );
    const result = await createResendMail({
      apiKey: "re_SECRET",
      fetch: fn,
    }).send(MESSAGE);
    assert.equal(result.ok, false);
    assert.ok(!result.ok);
    assert.equal(result.reason, reason, String(status));
    assert.equal(result.retryable, retryable, String(status));
    const text = JSON.stringify(result);
    assert.ok(
      !text.includes("re_SECRET") && !text.includes("person@example.com"),
      text,
    );
  }
});

test("네트워크 오류와 시간 초과는 일시적 실패이다", async () => {
  const { fn } = fakeFetch(() => {
    throw new TypeError("network");
  });
  const result = await createResendMail({ apiKey: "k", fetch: fn }).send(
    MESSAGE,
  );
  assert.deepEqual(result, {
    ok: false,
    reason: "unavailable",
    retryable: true,
  });
});

test("2xx인데 접수 번호가 없으면 성공으로 보지 않고 다시 보내지 않는다", async () => {
  for (const body of [{}, { id: "" }, { id: 5 }]) {
    const { fn } = fakeFetch(() => json(body, 200));
    const result = await createResendMail({ apiKey: "k", fetch: fn }).send(
      MESSAGE,
    );
    assert.ok(!result.ok);
    assert.equal(result.retryable, false);
  }
});

// --- POST /mail/test ---

class FakeMail implements MailPort {
  sent: MailMessage[] = [];
  result: SendResult = { ok: true, id: "msg-1" };
  async send(message: MailMessage): Promise<SendResult> {
    this.sent.push(message);
    return this.result;
  }
}

function mailSetup(mode: "sandbox" | "domain" = "domain") {
  const fixture = setup();
  const port = new FakeMail();
  fixture.deps.mail = () => ({
    port,
    sender: {
      from: "whatever.log <reports@example.com>",
      mode,
    },
  });
  return { ...fixture, port };
}

test("시험 메일은 로그인한 사용자 본인의 주소로만 가고, 응답에는 가린 주소만 담긴다", async () => {
  const { call, signIn, port } = mailSetup();
  const token = await signIn("sub-1", "person@example.com");

  // 본문에 다른 주소를 넣어도 쓰지 않는다(스팸 중계 방지)
  const { status, json: body } = await call("POST", "/mail/test", {
    token,
    body: { to: "victim@example.org" },
  });

  assert.equal(status, 200);
  assert.deepEqual(body, {
    sent: true,
    to: "p***@example.com",
    mode: "domain",
  });
  assert.equal(port.sent.length, 1);
  assert.equal(port.sent[0].to, "person@example.com");
  assert.ok(!JSON.stringify(body).includes("person@example.com"));
  assert.match(port.sent[0].text, /시험 메일/);
});

test("로그인하지 않았으면 401이고 메일은 나가지 않는다. POST만 받는다", async () => {
  const { call, port } = mailSetup();
  assert.equal((await call("POST", "/mail/test")).status, 401);
  assert.equal(
    (await call("POST", "/mail/test", { token: "x".repeat(43) })).status,
    401,
  );
  const token = await mailSetup().signIn();
  assert.equal((await call("GET", "/mail/test", { token })).status, 405);
  assert.equal(port.sent.length, 0);
});

test("메일이 설정되지 않았거나 설정이 틀리면 503이고 다른 기능은 그대로이다", async () => {
  for (const mail of [
    undefined,
    () => {
      throw new MailConfigError("RESEND_API_KEY가 설정되지 않았습니다.");
    },
  ]) {
    const fixture = setup();
    fixture.deps.mail = mail;
    const token = await fixture.signIn();
    const warnings: string[] = [];
    const original = console.warn;
    console.warn = (...args: unknown[]) => {
      warnings.push(args.join(" "));
    };
    let status: number | null;
    let body: Json;
    try {
      ({ status, json: body } = await fixture.call("POST", "/mail/test", {
        token,
      }));
    } finally {
      console.warn = original;
    }
    assert.equal(warnings.length, 1); // 무엇이 빠졌는지는 서버 로그에 남는다
    assert.match(warnings[0], /^mail config: /);
    assert.equal(status, 503);
    assert.equal(body.error.code, "mail_not_configured");
    assert.equal((await fixture.call("GET", "/goals", { token })).status, 200);
  }
});

test("사용자별 하루 한도를 넘으면 429이고, 다음 날에는 다시 보낼 수 있다", async () => {
  const { call, signIn, port, clock } = mailSetup();
  const token = await signIn();
  for (let n = 0; n < LIMITS.testPerUserPerDay; n += 1) {
    assert.equal((await call("POST", "/mail/test", { token })).status, 200);
  }
  const blocked = await call("POST", "/mail/test", { token });
  assert.equal(blocked.status, 429);
  assert.equal(blocked.json.error.code, "daily_limit");
  assert.equal(port.sent.length, LIMITS.testPerUserPerDay);

  clock.now = new Date(clock.now.getTime() + DAY_MS);
  assert.equal((await call("POST", "/mail/test", { token })).status, 200);
});

test("다른 사용자의 발송은 내 한도를 쓰지 않지만, 서버 전체 한도는 함께 쓴다", async () => {
  const { call, signIn, sqlite, clock } = mailSetup();
  const first = await signIn("sub-1", "a@example.com");
  const second = await signIn("sub-2", "b@example.com");
  for (let n = 0; n < LIMITS.testPerUserPerDay; n += 1) {
    await call("POST", "/mail/test", { token: first });
  }
  assert.equal(
    (await call("POST", "/mail/test", { token: second })).status,
    200,
  );

  // 서버 전체 상한에 닿았다고 만든다(오늘 기록이 상한만큼 있다)
  const day = clock.now.toISOString().slice(0, 10);
  const user = sqlite.prepare("SELECT id FROM users LIMIT 1").get() as {
    id: number;
  };
  const have = (
    sqlite
      .prepare("SELECT COUNT(*) AS n FROM mail_sends WHERE sent_on = ?")
      .get(day) as { n: number }
  ).n;
  for (let n = have; n < LIMITS.perDayTotal; n += 1) {
    sqlite
      .prepare(
        "INSERT INTO mail_sends (user_id, kind, sent_on, token, created_at) VALUES (?, 'report', ?, ?, ?)",
      )
      .run(user.id, day, `fill-${n}`, clock.now.toISOString());
  }
  const third = await signIn("sub-3", "c@example.com");
  const blocked = await call("POST", "/mail/test", { token: third });
  assert.equal(blocked.status, 429);
  assert.equal(blocked.json.error.code, "service_daily_limit");
});

test("발송에 실패하면 잡아 둔 자리를 돌려주고, 실패 이유에 맞는 응답을 한다", async () => {
  const cases: [SendResult, number, string][] = [
    [
      { ok: false, reason: "unauthorized", retryable: false },
      502,
      "mail_not_configured",
    ],
    [{ ok: false, reason: "rejected", retryable: false }, 502, "mail_rejected"],
    [
      { ok: false, reason: "rate_limited", retryable: true },
      429,
      "provider_rate_limited",
    ],
    [
      { ok: false, reason: "unavailable", retryable: true },
      503,
      "mail_unavailable",
    ],
  ];
  for (const [result, status, code] of cases) {
    const { call, signIn, port, sqlite } = mailSetup();
    port.result = result;
    const token = await signIn();
    const response = await call("POST", "/mail/test", { token });
    assert.equal(response.status, status);
    assert.equal(response.json.error.code, code);
    assert.equal(
      (
        sqlite.prepare("SELECT COUNT(*) AS n FROM mail_sends").get() as {
          n: number;
        }
      ).n,
      0,
    );
  }
});

test("실패가 한도를 깎지 않아서, 실패를 여러 번 겪은 뒤에도 한도만큼 보낼 수 있다", async () => {
  const { call, signIn, port } = mailSetup();
  const token = await signIn();
  port.result = { ok: false, reason: "unavailable", retryable: true };
  for (let n = 0; n < LIMITS.testPerUserPerDay + 2; n += 1) {
    assert.equal((await call("POST", "/mail/test", { token })).status, 503);
  }
  port.result = { ok: true, id: "ok" };
  for (let n = 0; n < LIMITS.testPerUserPerDay; n += 1) {
    assert.equal((await call("POST", "/mail/test", { token })).status, 200);
  }
});

test("샌드박스 발신에서 거절되면 도메인 설정이 필요하다고 알린다", async () => {
  const { call, signIn, port } = mailSetup("sandbox");
  port.result = { ok: false, reason: "rejected", retryable: false };
  const token = await signIn();
  const { json: body } = await call("POST", "/mail/test", { token });
  assert.match(body.error.message, /도메인/);
});

test("성공한 발송은 접수 번호를 기록하고, 계정을 지우면 기록도 지워진다", async () => {
  const { call, signIn, sqlite, db } = mailSetup();
  const token = await signIn();
  await call("POST", "/mail/test", { token });
  const row = sqlite
    .prepare("SELECT kind, provider_id FROM mail_sends")
    .get() as { kind: string; provider_id: string };
  assert.deepEqual({ ...row }, { kind: "test", provider_id: "msg-1" });

  const user = sqlite.prepare("SELECT id FROM users").get() as { id: number };
  await deleteAccount(db as never, user.id);
  assert.equal(
    (
      sqlite.prepare("SELECT COUNT(*) AS n FROM mail_sends").get() as {
        n: number;
      }
    ).n,
    0,
  );
});

test("발송 기록에는 주소·제목·본문을 담는 칸이 없다", () => {
  const { sqlite } = setup();
  const columns = sqlite
    .prepare("PRAGMA table_info(mail_sends)")
    .all()
    .map((row) => row.name);
  assert.deepEqual(columns, [
    "id",
    "user_id",
    "kind",
    "sent_on",
    "token",
    "created_at",
    "provider_id",
  ]);
});

test("주소 가리기", () => {
  assert.equal(maskEmail("person@example.com"), "p***@example.com");
  assert.equal(maskEmail("a@b.co"), "a***@b.co");
  assert.equal(maskEmail("@x"), "***");
  assert.equal(maskEmail("nodomain"), "***");
});
