import type { Db, Statement } from "../db.ts";
import { LIMITS } from "./config.ts";
import {
  type LinkConfig,
  unsubscribeHeaders,
  unsubscribeUrl,
} from "./links.ts";
import { reserveSend, userKey } from "./quota.ts";
import { buildReport, type ReportGoal, renderReport } from "./report.ts";
import { latestOccurrence, type Occurrence } from "./schedule.ts";
import type { SubscriptionRow } from "./subscriptions.ts";
import { addressHash, isSuppressed } from "./suppression.ts";
import type { MailDeps } from "./testMail.ts";

/** 한 번 돈 결과(로그용 — 주소·이름은 담지 않는다). */
export interface DispatchSummary {
  due: number;
  sent: number;
  ended: number;
  limited: number;
  failed: number;
  retry: number;
  /** 쿼리 예산이 모자라 다음 실행으로 넘긴 구독 수. */
  deferred: number;
  /** 이 실행이 쓴 D1 쿼리 수(batch는 한 번). */
  queries: number;
  /** 메일·링크 설정이 없어 보내지 못했다. */
  notConfigured: boolean;
}

/** 발송 기록을 이만큼(일) 남긴다 — 같은 구간을 다시 보내지 않으려면 한 주기(최대 한 달)보다 길면 충분하다. */
export const REPORT_RETENTION_DAYS = 90;

/** `sending`인 채 이만큼(분) 지난 자리는 그 실행이 도중에 죽은 것으로 보고 다시 잡는다. */
export const STALE_CLAIM_MINUTES = 30;

/**
 * 접수됐는지 모르는 발송을 같은 멱등 키로 다시 보내도 되는 기간(시간, 첫 시도부터). 메일 서비스(Resend)가 멱등 키를 24시간 기억하므로 그보다 짧게 잡는다 —
 * 그 뒤에 같은 키로 보내면 두 번째 메일이 갈 수 있어, 기간이 지난 `unknown`·`sending`은 다시 보내지 않는다.
 */
export const RETRY_WINDOW_HOURS = 23;

/** 한 통을 보내는 데 드는 쿼리의 최대(자리 1 + 막힌 주소 1 + 발송 한도 3 + 보고서 2 + 결과 기록 1 + 예외 때 정리 1). */
export const SEND_COST = 9;

/** 한 쿼리에 묶는 값의 수(D1은 문장당 바인딩 100개까지). */
const IN_CHUNK = 90;

interface Candidate extends SubscriptionRow {
  email: string;
  google_sub: string;
  goal_name: string;
  goal_target: number;
  goal_weekdays: number;
  goal_start: string | null;
  goal_end: string | null;
  goal_created_at: string;
}

/**
 * 쿼리 수를 세는 DB. 무료 요금제의 D1은 Worker 호출 한 번에 쿼리 50회까지라(batch는 한 번), 발송은 예산(`LIMITS.queriesPerRun`) 안에서만 하고
 * 남은 것은 다음 실행(10분 뒤)에 넘긴다.
 */
function counting(db: Db): { db: Db; used: () => number } {
  let used = 0;
  const wrap = (statement: Statement): Statement => ({
    bind: (...values) => wrap(statement.bind(...values)),
    run: () => {
      used += 1;
      return statement.run();
    },
    first: <T>() => {
      used += 1;
      return statement.first<T>();
    },
    all: <T>() => {
      used += 1;
      return statement.all<T>();
    },
  });
  return {
    db: {
      prepare: (sql) => wrap(db.prepare(sql)),
      batch: (statements) => {
        used += 1;
        return db.batch(statements);
      },
    },
    used: () => used,
  };
}

/**
 * 구독을 끝내는 문장. **읽어 둔 버전(`updated_at`)일 때만** 끝낸다 — 보내는 사이 사용자가 다른 목표로 옮기거나 일정을 바꿨으면(같은 id, 새 updated_at)
 * 이전 목표의 종료 처리가 새 구독을 끝내지 않게.
 */
const endStatement = (
  db: Db,
  sub: { id: string; updated_at: string },
  reason: "goal_ended" | "suppressed",
  now: Date,
) =>
  db
    .prepare(
      "UPDATE mail_subscriptions SET status = 'ended', ended_reason = ?, updated_at = ? WHERE id = ? AND status = 'active' AND updated_at = ?",
    )
    .bind(reason, now.toISOString(), sub.id, sub.updated_at);

function chunks<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size)
    out.push(items.slice(i, i + size));
  return out;
}

/**
 * 지금 보낼 보고서를 보낸다(Cloudflare Cron이 10분마다 부른다).
 *
 * - 켜진 구독마다 **지금 이전의 가장 최근 발송**(보낼 날·시각·구간)을 구한다. 그 시각이 구독을 신청·변경한 시각보다 이르면 건너뛴다(신청하자마자 지난
 *   보고서가 가지 않게). 밀린 발송은 따라잡지 않고 가장 최근 것 하나만 보낸다(옛 보고서가 몰려 오지 않게).
 * - 이미 보낸 구간과 막힌 주소는 실행 처음에 **한 번에** 읽는다(구독 수와 상관없이 쿼리 몇 번). 보내는 동안에는 쿼리 예산을 세고, 닿으면 멈춰 남은 구독을
 *   다음 실행에 넘긴다.
 * - (구독, 보낼 날)을 `mail_reports`에 먼저 넣은 쪽만 보낸다 — Cron이 겹쳐도 한 번만 간다. 멱등 키도 같은 값이다. `sending`인 채 30분이 지난 자리는
 *   그 실행이 도중에 죽은 것으로 보고 다시 잡는다.
 * - 목표 기간: 구간이 종료일보다 뒤면 보내지 않고 끝낸다(`goal_ended`). 구간이 종료일을 덮으면 마지막 보고서를 보낸 뒤 끝낸다.
 * - 막힌 주소면 보내지 않고 끝낸다(`suppressed`). 발송 한도(서버 전체·사용자별)를 거친다.
 * - 실패: 거절은 그 구간을 `failed`로 두고 다시 보내지 않는다. 한도·일시적 실패는 자리를 풀어 다음 실행이 같은 멱등 키로 다시 보낸다
 *   (접수됐을 수 있는 실패는 발송 한도의 자리를 유지한다). 키 오류는 이번 실행을 멈춘다. 구독 하나에서 예외가 나도 자리를 풀고 다음 구독으로 간다.
 */
export async function dispatchReports(
  rawDb: Db,
  mail: (MailDeps & { links?: LinkConfig }) | null,
  now: Date,
): Promise<DispatchSummary> {
  const { db, used } = counting(rawDb);
  const summary: DispatchSummary = {
    due: 0,
    sent: 0,
    ended: 0,
    limited: 0,
    failed: 0,
    retry: 0,
    deferred: 0,
    queries: 0,
    notConfigured: false,
  };
  const remaining = () => LIMITS.queriesPerRun - used();
  const done = () => {
    summary.queries = used();
    return summary;
  };

  await db
    .prepare("DELETE FROM mail_reports WHERE created_at < ?")
    .bind(
      new Date(
        now.getTime() - REPORT_RETENTION_DAYS * 24 * 60 * 60 * 1000,
      ).toISOString(),
    )
    .run();
  const { results } = await db
    .prepare(
      "SELECT s.id, s.user_id, s.goal_id, s.frequency, s.weekday, s.day_of_month, s.send_time, s.timezone, s.status, s.ended_reason, " +
        "s.created_at, s.updated_at, u.email, u.google_sub, g.name AS goal_name, g.daily_target_minutes AS goal_target, " +
        "g.weekdays AS goal_weekdays, g.start_date AS goal_start, g.end_date AS goal_end, g.created_at AS goal_created_at " +
        "FROM mail_subscriptions s JOIN users u ON u.id = s.user_id " +
        "JOIN goals g ON g.user_id = s.user_id AND g.id = s.goal_id AND g.deleted_at IS NULL " +
        "WHERE s.status = 'active' ORDER BY s.updated_at, s.id",
    )
    .all<Candidate>();

  // 보낼 때가 된 구독(쿼리 없이 계산). 한 구독의 값이 이상해도(예: 시간대) 그 구독만 건너뛴다.
  const pending: { sub: Candidate; occurrence: Occurrence }[] = [];
  for (const sub of results) {
    try {
      const occurrence = latestOccurrence(sub, now);
      if (occurrence.at.getTime() >= Date.parse(sub.updated_at)) {
        pending.push({ sub, occurrence });
      }
    } catch (error) {
      console.warn(`report schedule error: ${String(error)}`);
    }
  }
  if (pending.length === 0) return done();

  // 이미 보낸(또는 다른 실행이 보내는 중인) 구간을 한 번에 읽는다.
  const windows: Windows = {
    staleBefore: new Date(
      now.getTime() - STALE_CLAIM_MINUTES * 60 * 1000,
    ).toISOString(),
    retrySince: new Date(
      now.getTime() - RETRY_WINDOW_HOURS * 60 * 60 * 1000,
    ).toISOString(),
  };
  const oldestKey = pending.reduce(
    (min, item) => (item.occurrence.key < min ? item.occurrence.key : min),
    pending[0].occurrence.key,
  );
  const reports = await db
    .prepare(
      "SELECT subscription_id, period_key, status, created_at, updated_at FROM mail_reports WHERE period_key >= ?",
    )
    .bind(oldestKey)
    .all<{
      subscription_id: string;
      period_key: string;
      status: string;
      created_at: string;
      updated_at: string;
    }>();
  const handled = new Set(
    reports.results
      .filter((row) => !retryable(row, windows))
      .map((row) => `${row.subscription_id}|${row.period_key}`),
  );
  // 다시 보내는 구간(이미 행이 있다) — 요청 전에 실패하면 행을 지우지 않고 unknown으로 되돌려 첫 시도 시각을 지킨다.
  const retrying = new Set(
    reports.results
      .filter((row) => retryable(row, windows))
      .map((row) => `${row.subscription_id}|${row.period_key}`),
  );
  const due = pending.filter(
    ({ sub, occurrence }) => !handled.has(`${sub.id}|${occurrence.key}`),
  );
  summary.due = due.length;
  if (due.length === 0) return done();

  // 막힌 주소도 한 번에(바인딩 한도에 맞춰 나눠서).
  const hashes = new Map<string, string>();
  for (const { sub } of due) {
    if (!hashes.has(sub.email))
      hashes.set(sub.email, await addressHash(sub.email));
  }
  const suppressed = new Set<string>();
  for (const group of chunks([...new Set(hashes.values())], IN_CHUNK)) {
    const rows = await db
      .prepare(
        `SELECT address_hash FROM mail_suppressions WHERE address_hash IN (${group.map(() => "?").join(", ")})`,
      )
      .bind(...group)
      .all<{ address_hash: string }>();
    for (const row of rows.results) suppressed.add(row.address_hash);
  }

  for (let index = 0; index < due.length; index++) {
    const { sub, occurrence } = due[index];
    if (remaining() < 1) {
      summary.deferred += due.length - index;
      break;
    }
    if (sub.goal_end !== null && occurrence.period.start > sub.goal_end) {
      await endStatement(db, sub, "goal_ended", now).run();
      summary.ended += 1;
      continue;
    }
    if (suppressed.has(hashes.get(sub.email) as string)) {
      await endStatement(db, sub, "suppressed", now).run();
      summary.ended += 1;
      continue;
    }
    if (!mail?.links) {
      summary.notConfigured = true;
      break;
    }
    if (remaining() < SEND_COST) {
      summary.deferred += due.length - index;
      break;
    }
    const outcome = await sendOne(
      db,
      mail as MailDeps & { links: LinkConfig },
      sub,
      occurrence,
      now,
      windows,
      retrying.has(`${sub.id}|${occurrence.key}`),
    );
    if (outcome === "sent") summary.sent += 1;
    else if (outcome === "ended") summary.ended += 1;
    else if (outcome === "sent_final") {
      summary.sent += 1;
      summary.ended += 1;
    } else if (outcome === "limited") summary.limited += 1;
    else if (outcome === "failed") summary.failed += 1;
    else if (outcome === "retry") summary.retry += 1;
    else if (outcome === "stop") {
      summary.retry += 1;
      break;
    }
  }
  return done();
}

interface Windows {
  /** 이보다 오래된 `sending`은 그 실행이 죽은 것으로 본다. */
  staleBefore: string;
  /** 첫 시도가 이보다 늦은 구간만 같은 멱등 키로 다시 보낸다. */
  retrySince: string;
}

/**
 * 다시 보낼 구간인가: 첫 시도가 멱등 키의 유효 기간 안이고, 결과를 모르거나(`unknown`) 도중에 죽은 실행이 남긴 오래된 `sending`이다.
 * 그 밖(`sent`·`failed`, 보내는 중인 `sending`, 기간이 지난 것)은 처리된 것으로 본다.
 */
function retryable(
  row: { status: string; created_at: string; updated_at: string },
  windows: Windows,
): boolean {
  if (row.created_at < windows.retrySince) return false;
  return (
    row.status === "unknown" ||
    (row.status === "sending" && row.updated_at < windows.staleBefore)
  );
}

type SendOutcome =
  | "sent"
  | "sent_final"
  | "ended"
  | "skipped"
  | "limited"
  | "failed"
  | "retry"
  | "stop";

/**
 * 한 구독의 한 구간을 보낸다.
 * - 메일 요청을 하기 **전**의 실패(한도·보고서 계산·예외)는 자리와 발송 한도를 모두 돌려준다 — 보내지 않았으니 다시 보내도 된다.
 * - 요청을 **한 뒤** 결과를 모르면(`unavailable`, 예외) 구간을 `unknown`으로 두고 발송 한도의 자리를 유지한다. 멱등 키가 살아 있는 동안만 다시 보낸다.
 * - 서비스가 "같은 키로 다른 내용"(409 `invalid_idempotent_request`)이라고 하면 첫 요청이 이미 접수된 것이다 — 진행 기록이 그사이 바뀌어 본문이
 *   달라졌을 뿐이므로 보낸 것으로 기록한다. 접수 번호 없는 2xx(`no_id`)도 접수된 것으로 본다.
 */
async function sendOne(
  db: Db,
  mail: MailDeps & { links: LinkConfig },
  sub: Candidate,
  occurrence: Occurrence,
  now: Date,
  windows: Windows,
  /** 전에 시도한 구간을 다시 보내는가(행이 이미 있다). */
  retry: boolean,
): Promise<SendOutcome> {
  const stamp = now.toISOString();
  // 자리 잡기: 없으면 넣고, 다시 보낼 구간(결과 모름·죽은 실행의 오래된 sending)이면 다시 잡는다. 바뀐 행이 없으면 다른 실행의 것이다.
  // created_at(첫 시도)은 다시 잡아도 바꾸지 않는다.
  const claimed = await db
    .prepare(
      "INSERT INTO mail_reports (subscription_id, period_key, status, created_at, updated_at) VALUES (?1, ?2, 'sending', ?3, ?3) " +
        "ON CONFLICT(subscription_id, period_key) DO UPDATE SET status = 'sending', updated_at = excluded.updated_at " +
        "WHERE mail_reports.created_at >= ?5 AND (mail_reports.status = 'unknown' OR " +
        "(mail_reports.status = 'sending' AND mail_reports.updated_at < ?4))",
    )
    .bind(
      sub.id,
      occurrence.key,
      stamp,
      windows.staleBefore,
      windows.retrySince,
    )
    .run();
  if (claimed.meta.changes === 0) return "skipped";
  // 자리 풀기: 처음 시도면 행을 지우고, 다시 보내던 구간이면 unknown으로 되돌린다(전에 한 요청이 접수됐을 수 있고, 첫 시도 시각을 지켜야 한다).
  const unclaim = () =>
    retry
      ? db
          .prepare(
            "UPDATE mail_reports SET status = 'unknown', updated_at = ? WHERE subscription_id = ? AND period_key = ? AND status = 'sending'",
          )
          .bind(stamp, sub.id, occurrence.key)
      : db
          .prepare(
            "DELETE FROM mail_reports WHERE subscription_id = ? AND period_key = ? AND status = 'sending'",
          )
          .bind(sub.id, occurrence.key);
  const mark = (
    status: "sent" | "failed" | "unknown",
    providerId: string | null,
  ) =>
    db
      .prepare(
        "UPDATE mail_reports SET status = ?, provider_id = ?, updated_at = ? WHERE subscription_id = ? AND period_key = ?",
      )
      .bind(status, providerId, stamp, sub.id, occurrence.key);

  let token: string | null = null;
  let requested = false;
  const release = () =>
    db.prepare("DELETE FROM mail_sends WHERE token = ?").bind(token);
  try {
    // 실행 처음에 읽은 막힌 주소 뒤에 웹훅이 막았을 수 있다 — 보내기 직전에 다시 본다.
    if (await isSuppressed(db, sub.email)) {
      await db.batch([unclaim(), endStatement(db, sub, "suppressed", now)]);
      return "ended";
    }
    const reserved = await reserveSend(db, {
      key: await userKey(sub.google_sub),
      kind: "report",
      perUserPerDay: LIMITS.reportPerUserPerDay,
      now,
    });
    if (!reserved.ok) {
      await unclaim().run();
      return "limited";
    }
    token = reserved.token;

    const goal: ReportGoal = {
      name: sub.goal_name,
      daily_target_minutes: sub.goal_target,
      weekdays: sub.goal_weekdays,
      start_date: sub.goal_start,
      end_date: sub.goal_end,
      created_at: sub.goal_created_at,
    };
    const data = await buildReport(
      db,
      sub.user_id,
      sub.goal_id,
      goal,
      occurrence.period,
      sub.timezone,
    );
    const final =
      sub.goal_end !== null && occurrence.period.end >= sub.goal_end;
    const link = await unsubscribeUrl(mail.links, sub.id);
    const body = renderReport({
      goalName: sub.goal_name,
      frequency: sub.frequency,
      period: occurrence.period,
      data,
      timezone: sub.timezone,
      unsubscribeUrl: link,
      final,
    });
    requested = true;
    const result = await mail.port.send({
      from: mail.sender.from,
      to: sub.email,
      subject: body.subject,
      text: body.text,
      html: body.html,
      idempotencyKey: `report-${sub.id}-${occurrence.key}`,
      headers: unsubscribeHeaders(link),
    });

    const accepted =
      result.ok ||
      (result.reason === "unavailable" && result.detail === "no_id") ||
      (result.reason === "rejected" &&
        result.detail === "invalid_idempotent_request");
    if (accepted) {
      // 결과 기록은 한 번에(쿼리 하나): 발송 한도에 접수 번호, 구간은 sent, 마지막 보고서면 구독을 끝낸다.
      const providerId = result.ok ? result.id : null;
      await db.batch([
        ...(providerId
          ? [
              db
                .prepare(
                  "UPDATE mail_sends SET provider_id = ? WHERE token = ?",
                )
                .bind(providerId, token),
            ]
          : []),
        mark("sent", providerId),
        ...(final ? [endStatement(db, sub, "goal_ended", now)] : []),
      ]);
      return final ? "sent_final" : "sent";
    }
    console.warn(`report failed: ${result.reason} ${result.detail ?? ""}`);
    if (
      result.reason === "unavailable" ||
      result.detail === "concurrent_idempotent_requests"
    ) {
      // 접수됐는지 모른다(같은 키의 다른 요청이 처리 중인 경우 포함) — unknown으로 두고 발송 한도의 자리를 유지한다.
      await mark("unknown", null).run();
      return "retry";
    }
    if (result.reason === "rejected") {
      await db.batch([release(), mark("failed", null)]);
      return "failed";
    }
    // 접수되지 않았음이 확실한 실패(서비스 한도·키 오류): 자리와 발송 한도를 돌려주고 다음 실행이 다시 보낸다.
    await db.batch([unclaim(), release()]);
    return result.reason === "unauthorized" ? "stop" : "retry";
  } catch (error) {
    console.warn(`report error: ${String(error)}`);
    try {
      if (requested) {
        // 요청 뒤의 예외: 접수됐을 수 있다 — unknown으로 두고 발송 한도의 자리를 유지한다.
        await mark("unknown", null).run();
      } else {
        // 요청 전의 예외: 보내지 않았다 — 자리와 발송 한도를 모두 돌려준다.
        await db.batch(token ? [unclaim(), release()] : [unclaim()]);
      }
    } catch {
      // 정리하지 못해도 30분 뒤 다른 실행이 다시 잡는다(STALE_CLAIM_MINUTES, 멱등 키 기간 안에서만)
    }
    return "retry";
  }
}
