import type { Db } from "../db.ts";
import { type GoalInput, MAX_GOALS } from "./goalInput.ts";

const TOMBSTONE_DAYS = 30;

interface GoalRow {
  id: string;
  name: string;
  daily_target_minutes: number;
  weekdays: number;
  revision: number;
  updated_at: string;
  deleted_at: string | null;
}

/** 응답에 담는 목표. 삭제된 목표는 다른 기기가 삭제를 알 수 있게 id·revision·삭제 표시만 준다. */
export type GoalView =
  | {
      id: string;
      deleted: false;
      name: string;
      daily_target_minutes: number;
      weekdays: number[];
      revision: number;
      updated_at: string;
    }
  | { id: string; deleted: true; revision: number; updated_at: string };

export type GoalResult =
  | { ok: true; status: 200 | 201; goal: GoalView }
  | {
      ok: false;
      status: 404 | 409;
      code: string;
      message: string;
      current?: GoalView;
    };

export const weekdayList = (bits: number): number[] =>
  [0, 1, 2, 3, 4, 5, 6].filter((day) => (bits & (1 << day)) !== 0);

function view(row: GoalRow): GoalView {
  return row.deleted_at === null
    ? {
        id: row.id,
        deleted: false,
        name: row.name,
        daily_target_minutes: row.daily_target_minutes,
        weekdays: weekdayList(row.weekdays),
        revision: row.revision,
        updated_at: row.updated_at,
      }
    : {
        id: row.id,
        deleted: true,
        revision: row.revision,
        updated_at: row.updated_at,
      };
}

const SELECT =
  "SELECT id, name, daily_target_minutes, weekdays, revision, updated_at, deleted_at FROM goals";

/** 30일이 지난 삭제 표시를 지운다. 목록을 읽거나 목표를 지울 때마다 하므로, 더 지울 목표가 없어도 정리된다. */
async function purgeExpiredTombstones(
  db: Db,
  userId: number,
  now: Date,
): Promise<void> {
  const cutoff = new Date(
    now.getTime() - TOMBSTONE_DAYS * 24 * 60 * 60 * 1000,
  ).toISOString();
  await db
    .prepare(
      "DELETE FROM goals WHERE user_id = ? AND deleted_at IS NOT NULL AND deleted_at <= ?",
    )
    .bind(userId, cutoff)
    .run();
}

export async function listGoals(
  db: Db,
  userId: number,
  now: Date,
): Promise<GoalView[]> {
  await purgeExpiredTombstones(db, userId, now);
  const { results } = await db
    .prepare(`${SELECT} WHERE user_id = ? ORDER BY created_at, id`)
    .bind(userId)
    .all<GoalRow>();
  return results.map(view);
}

const find = (db: Db, userId: number, id: string) =>
  db
    .prepare(`${SELECT} WHERE user_id = ? AND id = ?`)
    .bind(userId, id)
    .first<GoalRow>();

const isUniqueViolation = (error: unknown): boolean =>
  error instanceof Error && /UNIQUE constraint failed/i.test(error.message);

const duplicateName = (): GoalResult => ({
  ok: false,
  status: 409,
  code: "duplicate_name",
  message: "같은 이름의 목표가 이미 있습니다.",
});

const conflict = (row: GoalRow, whenLive: string): GoalResult => ({
  ok: false,
  status: 409,
  code: row.deleted_at === null ? "conflict" : "goal_deleted",
  message: row.deleted_at === null ? whenLive : "삭제된 목표입니다.",
  current: view(row),
});

/**
 * 목표를 만들거나(`baseRevision` 0) 수정한다(현재 revision과 같을 때만). 두 기기가 동시에 고치면 늦은 쪽은 409와
 * 서버의 현재 값을 받아, 합쳐서 다시 보낼 수 있다. 만드는 요청을 재시도(같은 내용)하면 200으로 같은 결과를 준다.
 */
export async function putGoal(
  db: Db,
  userId: number,
  id: string,
  input: GoalInput,
  now: Date,
): Promise<GoalResult> {
  const stamp = now.toISOString();
  const existing = await find(db, userId, id);

  if (input.baseRevision === 0) {
    if (existing) {
      const same =
        existing.deleted_at === null &&
        existing.revision === 1 &&
        existing.name === input.name &&
        existing.daily_target_minutes === input.dailyTargetMinutes &&
        existing.weekdays === input.weekdays;
      if (same) return { ok: true, status: 200, goal: view(existing) };
      return conflict(
        existing,
        "이미 있는 목표입니다. 서버의 값을 확인하세요.",
      );
    }
    try {
      const result = await db
        .prepare(
          "INSERT INTO goals (user_id, id, name, name_key, daily_target_minutes, weekdays, revision, created_at, updated_at) " +
            "SELECT ?, ?, ?, ?, ?, ?, 1, ?, ? " +
            "WHERE (SELECT COUNT(*) FROM goals WHERE user_id = ? AND deleted_at IS NULL) < ?",
        )
        .bind(
          userId,
          id,
          input.name,
          input.nameKey,
          input.dailyTargetMinutes,
          input.weekdays,
          stamp,
          stamp,
          userId,
          MAX_GOALS,
        )
        .run();
      if (result.meta.changes === 0) {
        return {
          ok: false,
          status: 409,
          code: "too_many_goals",
          message: `목표는 ${MAX_GOALS}개까지 만들 수 있습니다.`,
        };
      }
    } catch (error) {
      if (isUniqueViolation(error)) return duplicateName();
      throw error;
    }
    return {
      ok: true,
      status: 201,
      goal: view((await find(db, userId, id)) as GoalRow),
    };
  }

  if (!existing) {
    return {
      ok: false,
      status: 404,
      code: "not_found",
      message: "없는 목표입니다.",
    };
  }
  const stale = "다른 기기에서 먼저 바뀌었습니다. 서버의 값을 확인하세요.";
  if (
    existing.deleted_at !== null ||
    existing.revision !== input.baseRevision
  ) {
    return conflict(existing, stale);
  }
  try {
    const result = await db
      .prepare(
        "UPDATE goals SET name = ?, name_key = ?, daily_target_minutes = ?, weekdays = ?, " +
          "revision = revision + 1, updated_at = ? " +
          "WHERE user_id = ? AND id = ? AND revision = ? AND deleted_at IS NULL",
      )
      .bind(
        input.name,
        input.nameKey,
        input.dailyTargetMinutes,
        input.weekdays,
        stamp,
        userId,
        id,
        input.baseRevision,
      )
      .run();
    if (result.meta.changes === 0) {
      return conflict((await find(db, userId, id)) as GoalRow, stale);
    }
  } catch (error) {
    if (isUniqueViolation(error)) return duplicateName();
    throw error;
  }
  return {
    ok: true,
    status: 200,
    goal: view((await find(db, userId, id)) as GoalRow),
  };
}

/**
 * 목표를 삭제한다: 이름을 지우고 삭제 표시만 남기며(다른 기기가 알 수 있게), 그 목표의 달성 줄은 바로 지운다.
 * 30일이 지난 삭제 표시도 함께 정리한다. 이미 삭제됐으면 true(여러 번 보내도 같다), 없는 목표면 false.
 */
export async function deleteGoal(
  db: Db,
  userId: number,
  id: string,
  now: Date,
): Promise<boolean> {
  await purgeExpiredTombstones(db, userId, now);
  const existing = await find(db, userId, id);
  if (!existing) return false;
  if (existing.deleted_at !== null) return true;
  const stamp = now.toISOString();
  await db.batch([
    db
      .prepare("DELETE FROM progress WHERE user_id = ? AND goal_id = ?")
      .bind(userId, id),
    db
      .prepare(
        "UPDATE goals SET name = '', name_key = '', deleted_at = ?, revision = revision + 1, updated_at = ? " +
          "WHERE user_id = ? AND id = ? AND deleted_at IS NULL",
      )
      .bind(stamp, stamp, userId, id),
  ]);
  return true;
}
