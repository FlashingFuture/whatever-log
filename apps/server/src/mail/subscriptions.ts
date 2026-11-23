import type { Db } from "../db.ts";
import { LIMITS } from "./config.ts";
import type { Frequency, SubscriptionInput } from "./subscriptionInput.ts";
import { todayIn } from "./subscriptionInput.ts";
import { addressHash, isSuppressed } from "./suppression.ts";

export type SubscriptionStatus = "active" | "paused" | "ended";
export type EndedReason =
  | "goal_deleted"
  | "goal_ended"
  | "unsubscribed"
  | "suppressed";

export interface SubscriptionRow {
  id: string;
  user_id: number;
  goal_id: string;
  frequency: Frequency;
  weekday: number | null;
  day_of_month: number | null;
  send_time: string;
  timezone: string;
  status: SubscriptionStatus;
  ended_reason: EndedReason | null;
  created_at: string;
  updated_at: string;
}

/** 응답에 싣는 구독. id(수신 거부 서명의 대상)는 화면에 필요 없어 싣지 않는다. */
export interface SubscriptionView {
  goal_id: string;
  frequency: Frequency;
  weekday: number | null;
  day_of_month: number | null;
  send_time: string;
  timezone: string;
  status: SubscriptionStatus;
  ended_reason: EndedReason | null;
  created_at: string;
  updated_at: string;
}

export function view(row: SubscriptionRow): SubscriptionView {
  return {
    goal_id: row.goal_id,
    frequency: row.frequency,
    weekday: row.weekday,
    day_of_month: row.day_of_month,
    send_time: row.send_time,
    timezone: row.timezone,
    status: row.status,
    ended_reason: row.ended_reason,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

const COLUMNS =
  "id, user_id, goal_id, frequency, weekday, day_of_month, send_time, timezone, status, ended_reason, created_at, updated_at";
const SELECT = `SELECT ${COLUMNS} FROM mail_subscriptions`;

export function findSubscription(
  db: Db,
  userId: number,
): Promise<SubscriptionRow | null> {
  return db
    .prepare(`${SELECT} WHERE user_id = ?`)
    .bind(userId)
    .first<SubscriptionRow>();
}

export function findSubscriptionById(
  db: Db,
  id: string,
): Promise<SubscriptionRow | null> {
  return db.prepare(`${SELECT} WHERE id = ?`).bind(id).first<SubscriptionRow>();
}

/** 매일 보고서를 더 받을 수 있는가(이 사용자를 빼고 센다 — 이미 매일인 사용자가 시각만 바꾸는 것은 막지 않는다). */
export async function dailyAvailable(db: Db, userId: number): Promise<boolean> {
  const row = await db
    .prepare(
      "SELECT COUNT(*) AS n FROM mail_subscriptions WHERE status = 'active' AND frequency = 'daily' AND user_id != ?",
    )
    .bind(userId)
    .first<{ n: number }>();
  return (row?.n ?? 0) < LIMITS.dailySubscribers;
}

/** 구독할 수 있는 사람인가 — 로그인한 사용자의 주소가 보내지 않을 목록에 있으면 신청·다시 켜기를 막는다. */
export interface MailUser {
  id: number;
  email: string;
  googleSub: string;
}

export type Refusal = {
  ok: false;
  status: number;
  code: string;
  message: string;
  current?: SubscriptionView;
};

export function refusal(
  status: number,
  code: string,
  message: string,
  current?: SubscriptionView,
): Refusal {
  return { ok: false, status, code, message, current };
}

const suppressedRefusal = () =>
  refusal(
    409,
    "mail_suppressed",
    "이 주소로 보낸 메일이 반송됐거나 스팸으로 신고되어 보고서 메일을 보낼 수 없어요.",
  );

const goalNotFound = () =>
  refusal(
    404,
    "goal_not_found",
    "서버에 없는 목표예요. 목표를 동기화한 뒤 다시 시도해 주세요.",
  );

/**
 * 구독 핸들러를 감싸는 가드: 로그인한 사용자의 계정 정보를 읽고, 보내지 않을 주소(반송·신고)면 핸들러를 부르지 않고 거절한다. 읽기(GET)·끄기·지우기는
 * 막지 않도록 `blockSuppressed`로 고른다. 가드는 읽기 쉽게 하려는 것이고, "사용자당 하나"의 보장은 DB 제약(user_id UNIQUE)이 한다.
 */
export function withSubscriptionGuard<T>(
  handler: (user: MailUser) => Promise<T | Refusal>,
  options: { blockSuppressed: boolean },
): (db: Db, userId: number) => Promise<T | Refusal> {
  return async (db, userId) => {
    const row = await db
      .prepare("SELECT id, email, google_sub FROM users WHERE id = ?")
      .bind(userId)
      .first<{ id: number; email: string; google_sub: string }>();
    if (!row) {
      return refusal(
        401,
        "invalid_token",
        "로그인이 필요합니다. 다시 로그인해 주세요.",
      );
    }
    if (options.blockSuppressed && (await isSuppressed(db, row.email))) {
      return suppressedRefusal();
    }
    return handler({ id: row.id, email: row.email, googleSub: row.google_sub });
  };
}

export type PutResult =
  | { ok: true; row: SubscriptionRow; created: boolean }
  | Refusal;

/**
 * 구독을 만들거나 바꾼다(사용자당 하나). 저장은 한 문장이다:
 * - 없으면 만들고, 있으면 고친다(`ON CONFLICT(user_id)`). 끝났거나 꺼진 구독도 다시 켜진다(`active`).
 * - 다른 목표를 구독 중이면 `replace`일 때만 옮긴다 — 아니면 고치지 않고 409와 지금 구독을 돌려준다(화면이 "옮길까요?"를 묻는다).
 * - 매일이면 매일 구독자 상한을 같은 문장에서 확인한다(동시에 신청이 몰려도 넘지 않는다).
 * 목표는 이 사용자의 살아 있는 목표여야 하고, 기간이 이미 끝난 목표는 받지 않는다(그 사용자의 시간대 기준 오늘).
 */
export async function putSubscription(
  db: Db,
  user: MailUser,
  input: SubscriptionInput,
  now: Date,
): Promise<PutResult> {
  const goal = await db
    .prepare(
      "SELECT end_date FROM goals WHERE user_id = ? AND id = ? AND deleted_at IS NULL",
    )
    .bind(user.id, input.goalId)
    .first<{ end_date: string | null }>();
  if (!goal) return goalNotFound();
  if (goal.end_date !== null && goal.end_date < todayIn(input.timezone, now)) {
    return refusal(
      409,
      "goal_ended",
      "기간이 끝난 목표는 보고서를 받을 수 없어요.",
    );
  }

  const id = crypto.randomUUID();
  const stamp = now.toISOString();
  const suppressed = await addressHash(user.email);
  // 확인과 저장을 한 문장에서 한다: 목표가 살아 있고, 주소가 막히지 않았고, (매일이면) 상한 안일 때만 쓴다 — 위의 확인 뒤에 목표가 지워지거나
  // 반송·신고가 와도 살아 있는 구독이 생기지 않는다. 쓴 행은 RETURNING으로 받는다(뒤이은 조회 사이에 지워질 수 있다).
  const row = await db
    .prepare(
      "INSERT INTO mail_subscriptions (id, user_id, goal_id, frequency, weekday, day_of_month, send_time, timezone, status, ended_reason, created_at, updated_at) " +
        "SELECT ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'active', NULL, ?9, ?9 " +
        "WHERE (?4 != 'daily' OR (SELECT COUNT(*) FROM mail_subscriptions WHERE status = 'active' AND frequency = 'daily' AND user_id != ?2) < ?10) " +
        "AND EXISTS (SELECT 1 FROM goals WHERE user_id = ?2 AND id = ?3 AND deleted_at IS NULL) " +
        "AND NOT EXISTS (SELECT 1 FROM mail_suppressions WHERE address_hash = ?12) " +
        "ON CONFLICT(user_id) DO UPDATE SET goal_id = excluded.goal_id, frequency = excluded.frequency, weekday = excluded.weekday, " +
        "day_of_month = excluded.day_of_month, send_time = excluded.send_time, timezone = excluded.timezone, status = 'active', " +
        "ended_reason = NULL, updated_at = excluded.updated_at " +
        // 다른 목표의 살아 있는 구독은 replace일 때만 옮긴다
        "WHERE mail_subscriptions.goal_id = excluded.goal_id OR mail_subscriptions.status = 'ended' OR ?11 " +
        `RETURNING ${COLUMNS}`,
    )
    .bind(
      id,
      user.id,
      input.goalId,
      input.frequency,
      input.weekday,
      input.dayOfMonth,
      input.sendTime,
      input.timezone,
      stamp,
      LIMITS.dailySubscribers,
      input.replace ? 1 : 0,
      suppressed,
    )
    .first<SubscriptionRow>();
  if (row) {
    return { ok: true, row, created: row.id === id };
  }
  // 쓰지 않은 이유를 가린다(앞의 확인 뒤에 바뀐 것부터).
  if (await isSuppressed(db, user.email)) return suppressedRefusal();
  const live = await db
    .prepare(
      "SELECT 1 AS present FROM goals WHERE user_id = ? AND id = ? AND deleted_at IS NULL",
    )
    .bind(user.id, input.goalId)
    .first();
  if (!live) return goalNotFound();
  const current = await findSubscription(db, user.id);
  if (
    current &&
    current.goal_id !== input.goalId &&
    current.status !== "ended" &&
    !input.replace
  ) {
    return refusal(
      409,
      "subscription_exists",
      "이미 다른 목표의 보고서를 받고 있어요. 이 목표로 옮길까요?",
      view(current),
    );
  }
  return refusal(
    409,
    "daily_full",
    "지금은 매일 보고서를 더 받을 수 없어요. 매주나 매월로 신청해 주세요.",
  );
}

export type StatusResult = { ok: true; row: SubscriptionRow } | Refusal;

/** 켜고 끈다. 끝난 구독(ended)은 다시 신청해야 한다(PUT). 매일 구독을 다시 켤 때는 매일 상한을 확인한다. */
export async function setSubscriptionStatus(
  db: Db,
  user: MailUser,
  status: "active" | "paused",
  now: Date,
): Promise<StatusResult> {
  const current = await findSubscription(db, user.id);
  if (!current) {
    return refusal(404, "not_found", "신청한 보고서 메일이 없어요.");
  }
  if (current.status === "ended") {
    return refusal(
      409,
      "subscription_ended",
      "끝난 구독이에요. 보고서를 다시 받으려면 새로 신청해 주세요.",
      view(current),
    );
  }
  // 다시 켤 때는 막힌 주소가 아닌지도 같은 문장에서 본다(앞의 가드 뒤에 반송·신고가 와도 되살아나지 않게).
  const row = await db
    .prepare(
      "UPDATE mail_subscriptions SET status = ?1, updated_at = ?2 WHERE user_id = ?3 AND status != 'ended' " +
        "AND (?1 = 'paused' OR frequency != 'daily' OR status = 'active' OR " +
        "(SELECT COUNT(*) FROM mail_subscriptions WHERE status = 'active' AND frequency = 'daily' AND user_id != ?3) < ?4) " +
        "AND (?1 = 'paused' OR NOT EXISTS (SELECT 1 FROM mail_suppressions WHERE address_hash = ?5)) " +
        `RETURNING ${COLUMNS}`,
    )
    .bind(
      status,
      now.toISOString(),
      user.id,
      LIMITS.dailySubscribers,
      await addressHash(user.email),
    )
    .first<SubscriptionRow>();
  if (row) return { ok: true, row };
  // 바꾸지 않은 이유를 가린다(앞의 확인 뒤에 지워졌거나 끝났을 수 있다).
  const latest = await findSubscription(db, user.id);
  if (!latest) {
    return refusal(404, "not_found", "신청한 보고서 메일이 없어요.");
  }
  if (latest.status === "ended") {
    return refusal(
      409,
      "subscription_ended",
      "끝난 구독이에요. 보고서를 다시 받으려면 새로 신청해 주세요.",
      view(latest),
    );
  }
  if (status === "active" && (await isSuppressed(db, user.email))) {
    return suppressedRefusal();
  }
  return refusal(
    409,
    "daily_full",
    "지금은 매일 보고서를 더 받을 수 없어요. 매주나 매월로 바꿔 주세요.",
    view(latest),
  );
}

/** 구독을 지운다(사용자가 그만둠). 지울 것이 없으면 false. */
export async function deleteSubscription(
  db: Db,
  userId: number,
): Promise<boolean> {
  const result = await db
    .prepare("DELETE FROM mail_subscriptions WHERE user_id = ?")
    .bind(userId)
    .run();
  return result.meta.changes > 0;
}

/** 목표를 지우면 그 목표의 구독을 끝낸다(`goal_deleted`) — 목표 삭제와 같은 배치에 넣는 문장. */
export function endForDeletedGoal(
  db: Db,
  userId: number,
  goalId: string,
  stamp: string,
) {
  return db
    .prepare(
      "UPDATE mail_subscriptions SET status = 'ended', ended_reason = 'goal_deleted', updated_at = ? " +
        "WHERE user_id = ? AND goal_id = ? AND status != 'ended'",
    )
    .bind(stamp, userId, goalId);
}

/** 수신 거부 링크로 끝낸다(`unsubscribed`). 이미 끝났으면 그대로 둔다(여러 번 눌러도 같다). 그 id의 구독이 있으면 true. */
export async function unsubscribeById(
  db: Db,
  id: string,
  now: Date,
): Promise<boolean> {
  const row = await findSubscriptionById(db, id);
  if (!row) return false;
  await db
    .prepare(
      "UPDATE mail_subscriptions SET status = 'ended', ended_reason = 'unsubscribed', updated_at = ? WHERE id = ? AND status != 'ended'",
    )
    .bind(now.toISOString(), id)
    .run();
  return true;
}
