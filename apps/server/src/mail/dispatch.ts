import type { Db } from "../db.ts";
import { LIMITS } from "./config.ts";
import {
  type LinkConfig,
  unsubscribeHeaders,
  unsubscribeUrl,
} from "./links.ts";
import { recordSent, releaseSend, reserveSend, userKey } from "./quota.ts";
import { buildReport, type ReportGoal, renderReport } from "./report.ts";
import { latestOccurrence } from "./schedule.ts";
import type { SubscriptionRow } from "./subscriptions.ts";
import { isSuppressed } from "./suppression.ts";
import type { MailDeps } from "./testMail.ts";

/** 한 번 돈 결과(로그용 — 주소·이름은 담지 않는다). */
export interface DispatchSummary {
  due: number;
  sent: number;
  ended: number;
  limited: number;
  failed: number;
  retry: number;
  /** 메일·링크 설정이 없어 보내지 못했다. */
  notConfigured: boolean;
}

/** 발송 기록을 이만큼(일) 남긴다 — 같은 구간을 다시 보내지 않으려면 한 주기(최대 한 달)보다 길면 충분하다. */
export const REPORT_RETENTION_DAYS = 90;

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

async function endSubscription(
  db: Db,
  id: string,
  reason: "goal_ended" | "suppressed",
  now: Date,
): Promise<void> {
  await db
    .prepare(
      "UPDATE mail_subscriptions SET status = 'ended', ended_reason = ?, updated_at = ? WHERE id = ? AND status = 'active'",
    )
    .bind(reason, now.toISOString(), id)
    .run();
}

/**
 * 지금 보낼 보고서를 보낸다(Cloudflare Cron이 10분마다 부른다).
 *
 * - 켜진 구독마다 **지금 이전의 가장 최근 발송**(보낼 날·시각·구간)을 구한다. 그 시각이 구독을 신청·변경한 시각보다 이르면 건너뛴다(신청하자마자 어제
 *   보고서가 가지 않게). 밀린 발송은 따라잡지 않고 가장 최근 것 하나만 보낸다(옛 보고서가 몰려 오지 않게).
 * - (구독, 보낼 날)을 `mail_reports`에 먼저 넣은 쪽만 보낸다 — Cron이 겹쳐도 한 번만 간다. 멱등 키도 같은 값으로 정한다.
 * - 목표 기간: 구간이 종료일보다 뒤면 보내지 않고 끝낸다(`goal_ended`). 구간이 종료일을 덮으면 마지막 보고서를 보낸 뒤 끝낸다.
 * - 막힌 주소면 보내지 않고 끝낸다(`suppressed`). 발송 한도(서버 전체·사용자별)를 거친다.
 * - 실패: 거절은 그 구간을 `failed`로 두고 다시 보내지 않는다. 한도·일시적 실패는 자리를 풀어 다음 실행이 같은 멱등 키로 다시 보낸다
 *   (접수됐을 수 있는 실패도 서비스가 같은 키를 한 번만 보낸다). 키 오류는 이번 실행을 멈춘다.
 */
export async function dispatchReports(
  db: Db,
  mail: (MailDeps & { links?: LinkConfig }) | null,
  now: Date,
): Promise<DispatchSummary> {
  const summary: DispatchSummary = {
    due: 0,
    sent: 0,
    ended: 0,
    limited: 0,
    failed: 0,
    retry: 0,
    notConfigured: false,
  };
  const oldest = new Date(
    now.getTime() - REPORT_RETENTION_DAYS * 24 * 60 * 60 * 1000,
  ).toISOString();
  await db
    .prepare("DELETE FROM mail_reports WHERE created_at < ?")
    .bind(oldest)
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

  for (const sub of results) {
    if (summary.sent >= LIMITS.reportsPerRun) break;
    const occurrence = latestOccurrence(sub, now);
    if (occurrence.at.getTime() < Date.parse(sub.updated_at)) continue;
    const sent = await db
      .prepare(
        "SELECT 1 AS present FROM mail_reports WHERE subscription_id = ? AND period_key = ?",
      )
      .bind(sub.id, occurrence.key)
      .first();
    if (sent) continue;
    summary.due += 1;

    if (sub.goal_end !== null && occurrence.period.start > sub.goal_end) {
      await endSubscription(db, sub.id, "goal_ended", now);
      summary.ended += 1;
      continue;
    }
    if (await isSuppressed(db, sub.email)) {
      await endSubscription(db, sub.id, "suppressed", now);
      summary.ended += 1;
      continue;
    }
    if (!mail?.links) {
      summary.notConfigured = true;
      break;
    }

    // 자리 잡기: 먼저 넣은 쪽만 보낸다.
    const stamp = now.toISOString();
    const claimed = await db
      .prepare(
        "INSERT INTO mail_reports (subscription_id, period_key, status, created_at, updated_at) VALUES (?, ?, 'sending', ?, ?) " +
          "ON CONFLICT(subscription_id, period_key) DO NOTHING",
      )
      .bind(sub.id, occurrence.key, stamp, stamp)
      .run();
    if (claimed.meta.changes === 0) continue;
    const unclaim = () =>
      db
        .prepare(
          "DELETE FROM mail_reports WHERE subscription_id = ? AND period_key = ? AND status = 'sending'",
        )
        .bind(sub.id, occurrence.key)
        .run();

    const reserved = await reserveSend(db, {
      key: await userKey(sub.google_sub),
      kind: "report",
      perUserPerDay: LIMITS.reportPerUserPerDay,
      now,
    });
    if (!reserved.ok) {
      await unclaim();
      summary.limited += 1;
      continue;
    }

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
    const result = await mail.port.send({
      from: mail.sender.from,
      to: sub.email,
      subject: body.subject,
      text: body.text,
      html: body.html,
      idempotencyKey: `report-${sub.id}-${occurrence.key}`,
      headers: unsubscribeHeaders(link),
    });

    if (result.ok) {
      await recordSent(db, reserved.token, result.id);
      await db
        .prepare(
          "UPDATE mail_reports SET status = 'sent', provider_id = ?, updated_at = ? WHERE subscription_id = ? AND period_key = ?",
        )
        .bind(result.id, stamp, sub.id, occurrence.key)
        .run();
      summary.sent += 1;
      if (final) {
        await endSubscription(db, sub.id, "goal_ended", now);
        summary.ended += 1;
      }
      continue;
    }
    console.warn(`report failed: ${result.reason} ${result.detail ?? ""}`);
    if (result.reason === "rejected") {
      await releaseSend(db, reserved.token);
      await db
        .prepare(
          "UPDATE mail_reports SET status = 'failed', updated_at = ? WHERE subscription_id = ? AND period_key = ?",
        )
        .bind(stamp, sub.id, occurrence.key)
        .run();
      summary.failed += 1;
      continue;
    }
    // 다시 보낼 실패: 자리를 풀어 다음 실행이 같은 멱등 키로 보낸다. 접수됐을 수 있는 실패(unavailable)는 발송 한도의 자리를 유지한다.
    await unclaim();
    if (result.reason !== "unavailable") {
      await releaseSend(db, reserved.token);
    }
    summary.retry += 1;
    if (result.reason === "unauthorized") break; // 설정 문제 — 이번 실행의 나머지도 같은 결과다
  }
  return summary;
}
