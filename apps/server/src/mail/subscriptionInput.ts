import { isUuid } from "../sync/goalInput.ts";

export const FREQUENCIES = ["daily", "weekly", "monthly"] as const;
export type Frequency = (typeof FREQUENCIES)[number];

/** 구독 신청·변경(`PUT /mail/subscription`). */
export interface SubscriptionInput {
  goalId: string;
  frequency: Frequency;
  /** 매주일 때만(월=0 … 일=6). */
  weekday: number | null;
  /** 매월일 때만(1~28). */
  dayOfMonth: number | null;
  /** `HH:MM`(사용자의 시간대). */
  sendTime: string;
  /** IANA 시간대(예: Asia/Seoul). */
  timezone: string;
  /** 이미 다른 목표를 구독 중이면 그 구독을 이 목표로 옮긴다(false면 409로 묻는다). */
  replace: boolean;
}

export type Parse<T> = { ok: true; value: T } | { ok: false; message: string };

const FIELDS = new Set([
  "goal_id",
  "frequency",
  "weekday",
  "day_of_month",
  "send_time",
  "timezone",
  "replace",
]);
const TIME = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
const ZONE = /^[A-Za-z][A-Za-z0-9_+-]*(\/[A-Za-z0-9_+-]+){0,2}$/;

const isInt = (value: unknown): value is number => Number.isInteger(value);

/** 런타임이 아는 IANA 시간대인가(`Asia/Seoul`, `UTC` …). 모양을 먼저 거르고, 실제 여부는 Intl에 묻는다. */
export function isTimeZone(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 64 || !ZONE.test(value)) {
    return false;
  }
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

function object(body: unknown): Record<string, unknown> | null {
  return typeof body === "object" && body !== null && !Array.isArray(body)
    ? (body as Record<string, unknown>)
    : null;
}

export function parseSubscriptionInput(
  body: unknown,
): Parse<SubscriptionInput> {
  const record = object(body);
  if (!record) return { ok: false, message: "본문은 JSON 객체여야 합니다." };
  const extra = Object.keys(record).filter((key) => !FIELDS.has(key));
  if (extra.length > 0) {
    return {
      ok: false,
      message: `알 수 없는 칸이 있습니다: ${extra.join(", ")}`,
    };
  }
  const {
    goal_id: goalId,
    frequency,
    weekday = null,
    day_of_month: dayOfMonth = null,
    send_time: sendTime,
    timezone,
    replace = false,
  } = record;
  if (typeof goalId !== "string" || !isUuid(goalId)) {
    return { ok: false, message: "goal_id는 서버 목표의 id(UUID)여야 합니다." };
  }
  if (!(FREQUENCIES as readonly unknown[]).includes(frequency)) {
    return {
      ok: false,
      message: "frequency는 daily·weekly·monthly 중 하나여야 합니다.",
    };
  }
  if (frequency === "weekly") {
    if (!isInt(weekday) || weekday < 0 || weekday > 6) {
      return {
        ok: false,
        message: "매주 보내려면 weekday가 0(월)~6(일)이어야 합니다.",
      };
    }
  } else if (weekday !== null) {
    return { ok: false, message: "weekday는 매주일 때만 보냅니다." };
  }
  if (frequency === "monthly") {
    if (!isInt(dayOfMonth) || dayOfMonth < 1 || dayOfMonth > 28) {
      return {
        ok: false,
        message: "매월 보내려면 day_of_month가 1~28이어야 합니다.",
      };
    }
  } else if (dayOfMonth !== null) {
    return { ok: false, message: "day_of_month는 매월일 때만 보냅니다." };
  }
  if (typeof sendTime !== "string" || !TIME.test(sendTime)) {
    return {
      ok: false,
      message: "send_time은 00:00~23:59의 HH:MM이어야 합니다.",
    };
  }
  if (!isTimeZone(timezone)) {
    return {
      ok: false,
      message: "timezone은 IANA 시간대 이름(예: Asia/Seoul)이어야 합니다.",
    };
  }
  if (typeof replace !== "boolean") {
    return { ok: false, message: "replace는 true 또는 false여야 합니다." };
  }
  return {
    ok: true,
    value: {
      goalId,
      frequency: frequency as Frequency,
      weekday: frequency === "weekly" ? (weekday as number) : null,
      dayOfMonth: frequency === "monthly" ? (dayOfMonth as number) : null,
      sendTime,
      timezone,
      replace,
    },
  };
}

/** 켜고 끄기(`PATCH /mail/subscription`): `{status: "active" | "paused"}`. */
export function parseStatusInput(body: unknown): Parse<"active" | "paused"> {
  const record = object(body);
  if (!record) return { ok: false, message: "본문은 JSON 객체여야 합니다." };
  const extra = Object.keys(record).filter((key) => key !== "status");
  if (extra.length > 0) {
    return {
      ok: false,
      message: `알 수 없는 칸이 있습니다: ${extra.join(", ")}`,
    };
  }
  if (record.status !== "active" && record.status !== "paused") {
    return { ok: false, message: "status는 active 또는 paused여야 합니다." };
  }
  return { ok: true, value: record.status };
}

/** 그 시간대의 오늘(`YYYY-MM-DD`). */
export function todayIn(timezone: string, now: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}
