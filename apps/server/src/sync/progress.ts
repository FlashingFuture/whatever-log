import type { Db } from "../db.ts";
import type { ProgressEntry } from "./progressInput.ts";

/** 사용자당 달성도를 보낼 수 있는 기기 수. 쓰지 않는 기기는 `DELETE /devices/{id}`로 지운다. */
export const MAX_DEVICES = 10;

export type PutProgressResult =
  | { ok: true; accepted: number; ignoredGoalIds: string[] }
  | { ok: false; code: "too_many_devices"; message: string };

/**
 * 이 기기의 (목표, 날짜) 줄들을 덮어쓴다. 없거나 삭제된 목표는 저장하지 않고 ignoredGoalIds로 알린다(다른
 * 기기에서 목표를 지운 직후에 흔히 생긴다). 기기마다 자기 줄만 쓰므로 다른 기기와 충돌하지 않는다.
 */
export async function putProgress(
  db: Db,
  userId: number,
  deviceId: string,
  entries: ProgressEntry[],
  now: Date,
): Promise<PutProgressResult> {
  const known = await db
    .prepare(
      "SELECT 1 AS present FROM progress WHERE user_id = ? AND device_id = ? LIMIT 1",
    )
    .bind(userId, deviceId)
    .first();
  if (!known) {
    const devices = await db
      .prepare(
        "SELECT COUNT(DISTINCT device_id) AS count FROM progress WHERE user_id = ?",
      )
      .bind(userId)
      .first<{ count: number }>();
    if ((devices?.count ?? 0) >= MAX_DEVICES) {
      return {
        ok: false,
        code: "too_many_devices",
        message: `기기는 ${MAX_DEVICES}대까지 연결할 수 있습니다. 쓰지 않는 기기를 지워 주세요.`,
      };
    }
  }

  const stamp = now.toISOString();
  const upserts = entries.map((entry) =>
    db
      .prepare(
        "INSERT INTO progress (user_id, goal_id, device_id, day, minutes, target_minutes, updated_at) " +
          "SELECT ?, id, ?, ?, ?, ?, ? FROM goals WHERE user_id = ? AND id = ? AND deleted_at IS NULL " +
          "ON CONFLICT(user_id, goal_id, device_id, day) DO UPDATE SET " +
          "minutes = excluded.minutes, target_minutes = excluded.target_minutes, updated_at = excluded.updated_at",
      )
      .bind(
        userId,
        deviceId,
        entry.day,
        entry.minutes,
        entry.targetMinutes,
        stamp,
        userId,
        entry.goalId,
      ),
  );
  const results = await db.batch(upserts);
  const ignored = new Set<string>();
  results.forEach((result, index) => {
    if (result.meta.changes === 0) ignored.add(entries[index].goalId);
  });
  return {
    ok: true,
    accepted:
      entries.length - results.filter((r) => r.meta.changes === 0).length,
    ignoredGoalIds: [...ignored],
  };
}

export interface DayProgress {
  goal_id: string;
  day: string;
  minutes: number;
  target_minutes: number;
  percent: number;
  devices: number;
}

/**
 * 구간의 목표·날짜별 합산(모든 기기의 분을 더한다). 목표량은 그날 가장 최근에 쓴 기기의 값이고(SQLite는
 * MAX(updated_at)와 함께 고른 맨몸 칼럼을 그 행에서 읽는다), 삭제된 목표는 제외한다.
 */
export async function getProgress(
  db: Db,
  userId: number,
  from: string,
  to: string,
): Promise<DayProgress[]> {
  const { results } = await db
    .prepare(
      "SELECT p.goal_id AS goal_id, p.day AS day, SUM(p.minutes) AS minutes, p.target_minutes AS target_minutes, " +
        "COUNT(*) AS devices, MAX(p.updated_at) AS latest " +
        "FROM progress p JOIN goals g ON g.user_id = p.user_id AND g.id = p.goal_id AND g.deleted_at IS NULL " +
        "WHERE p.user_id = ? AND p.day >= ? AND p.day <= ? " +
        "GROUP BY p.goal_id, p.day ORDER BY p.day, p.goal_id",
    )
    .bind(userId, from, to)
    .all<{
      goal_id: string;
      day: string;
      minutes: number;
      target_minutes: number;
      devices: number;
    }>();
  return results.map((row) => ({
    goal_id: row.goal_id,
    day: row.day,
    minutes: row.minutes,
    target_minutes: row.target_minutes,
    percent: Math.round((row.minutes * 100) / row.target_minutes),
    devices: row.devices,
  }));
}

/** 기기가 보낸 달성 줄을 모두 지운다(없어도 오류가 아니다). */
export async function deleteDevice(
  db: Db,
  userId: number,
  deviceId: string,
): Promise<void> {
  await db
    .prepare("DELETE FROM progress WHERE user_id = ? AND device_id = ?")
    .bind(userId, deviceId)
    .run();
}
