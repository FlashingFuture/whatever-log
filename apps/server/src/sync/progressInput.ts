import { isUuid } from "./goalInput.ts";

export const MAX_ENTRIES = 50;
export const MAX_RANGE_DAYS = 400;
const DAY_MS = 24 * 60 * 60 * 1000;
const DAY_FORMAT = /^\d{4}-\d{2}-\d{2}$/;

export interface ProgressEntry {
  goalId: string;
  day: string;
  minutes: number;
  targetMinutes: number;
}

export type PutProgressParse =
  | { ok: true; deviceId: string; entries: ProgressEntry[] }
  | { ok: false; message: string };

export type RangeParse =
  | { ok: true; from: string; to: string }
  | { ok: false; message: string };

const isInt = (value: unknown): value is number => Number.isInteger(value);

/** `YYYY-MM-DD`가 실제 달력의 날짜인지(2026-02-30 같은 값은 거른다). 맞으면 그 날의 UTC 자정(ms). */
function dayToMs(day: unknown): number | null {
  if (typeof day !== "string" || !DAY_FORMAT.test(day)) return null;
  const ms = Date.parse(`${day}T00:00:00.000Z`);
  return Number.isNaN(ms) || new Date(ms).toISOString().slice(0, 10) !== day
    ? null
    : ms;
}

/** 보낼 수 있는 날짜: 오늘(UTC)보다 하루 넘게 앞서지 않고, 400일보다 오래되지 않았다(시간대 차이를 하루 허용). */
function dayAllowed(ms: number, now: Date): boolean {
  const today = Math.floor(now.getTime() / DAY_MS) * DAY_MS;
  return ms <= today + DAY_MS && ms >= today - MAX_RANGE_DAYS * DAY_MS;
}

export function parsePutProgress(body: unknown, now: Date): PutProgressParse {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, message: "본문은 JSON 객체여야 합니다." };
  }
  const record = body as Record<string, unknown>;
  const extra = Object.keys(record).filter(
    (key) => key !== "device_id" && key !== "entries",
  );
  if (extra.length > 0) {
    return {
      ok: false,
      message: `알 수 없는 칸이 있습니다: ${extra.join(", ")}`,
    };
  }
  const { device_id: deviceId, entries } = record;
  if (typeof deviceId !== "string" || !isUuid(deviceId)) {
    return { ok: false, message: "device_id는 UUID v4여야 합니다." };
  }
  if (!Array.isArray(entries) || entries.length === 0) {
    return {
      ok: false,
      message: "entries는 비어 있지 않은 목록이어야 합니다.",
    };
  }
  if (entries.length > MAX_ENTRIES) {
    return {
      ok: false,
      message: `entries는 한 번에 ${MAX_ENTRIES}개까지 보낼 수 있습니다.`,
    };
  }
  const seen = new Set<string>();
  const parsed: ProgressEntry[] = [];
  for (const [index, entry] of entries.entries()) {
    const where = `entries[${index}]`;
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
      return { ok: false, message: `${where}는 객체여야 합니다.` };
    }
    const item = entry as Record<string, unknown>;
    const unknown = Object.keys(item).filter(
      (key) => !["goal_id", "day", "minutes", "target_minutes"].includes(key),
    );
    if (unknown.length > 0) {
      return {
        ok: false,
        message: `${where}에 알 수 없는 칸이 있습니다: ${unknown.join(", ")}`,
      };
    }
    if (typeof item.goal_id !== "string" || !isUuid(item.goal_id)) {
      return { ok: false, message: `${where}.goal_id는 UUID v4여야 합니다.` };
    }
    const ms = dayToMs(item.day);
    if (ms === null || !dayAllowed(ms, now)) {
      return {
        ok: false,
        message: `${where}.day는 최근 ${MAX_RANGE_DAYS}일 안의 YYYY-MM-DD여야 합니다.`,
      };
    }
    if (!isInt(item.minutes) || item.minutes < 0 || item.minutes > 1440) {
      return {
        ok: false,
        message: `${where}.minutes는 0~1440 정수여야 합니다.`,
      };
    }
    if (
      !isInt(item.target_minutes) ||
      item.target_minutes < 1 ||
      item.target_minutes > 1440
    ) {
      return {
        ok: false,
        message: `${where}.target_minutes는 1~1440 정수여야 합니다.`,
      };
    }
    const key = `${item.goal_id}|${item.day}`;
    if (seen.has(key)) {
      return { ok: false, message: `${where}가 같은 목표·날짜를 중복합니다.` };
    }
    seen.add(key);
    parsed.push({
      goalId: item.goal_id,
      day: item.day as string,
      minutes: item.minutes,
      targetMinutes: item.target_minutes,
    });
  }
  return { ok: true, deviceId, entries: parsed };
}

/** `GET /progress?from=&to=`의 구간. 두 날짜가 모두 있어야 하고 최대 400일이다. 모르는 파라미터는 거부한다. */
export function parseRange(params: URLSearchParams): RangeParse {
  for (const key of params.keys()) {
    if (key !== "from" && key !== "to") {
      return { ok: false, message: `알 수 없는 파라미터입니다: ${key}` };
    }
  }
  const from = params.get("from");
  const to = params.get("to");
  const fromMs = dayToMs(from);
  const toMs = dayToMs(to);
  if (fromMs === null || toMs === null) {
    return { ok: false, message: "from과 to는 YYYY-MM-DD여야 합니다." };
  }
  if (fromMs > toMs) {
    return { ok: false, message: "from은 to보다 늦을 수 없습니다." };
  }
  if ((toMs - fromMs) / DAY_MS >= MAX_RANGE_DAYS) {
    return {
      ok: false,
      message: `구간은 ${MAX_RANGE_DAYS}일을 넘을 수 없습니다.`,
    };
  }
  return { ok: true, from: from as string, to: to as string };
}
