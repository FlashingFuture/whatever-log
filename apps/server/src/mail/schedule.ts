/**
 * 보고서 일정의 시간 계산(순수 함수). 모든 날짜는 **구독의 시간대(IANA)** 기준 `YYYY-MM-DD`이고, 비교할 때만 UTC 시각으로 바꾼다.
 * 규칙(docs/goal-management.md "보고서 구간"): 매일 = 전날 하루, 매주 = 지난 월~일, 매월 = 지난달.
 */

import type { Frequency } from "./subscriptionInput.ts";

export interface ScheduleLike {
  frequency: Frequency;
  weekday: number | null;
  day_of_month: number | null;
  send_time: string;
  timezone: string;
}

export interface Period {
  /** 구간의 첫날과 마지막 날(양끝 포함). */
  start: string;
  end: string;
}

export interface Occurrence {
  /** 이 발송의 이름: 보낼 날(그 시간대의 날짜). (구독, 이 값)이 한 번만 보내는 단위다. */
  key: string;
  /** 보낼 시각(UTC). */
  at: Date;
  /** 보고서가 다루는 구간. */
  period: Period;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** 그 시간대에서 이 순간의 날짜와 자정부터 지난 분. */
export function localParts(
  instant: Date,
  timezone: string,
): { date: string; minutes: number } {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(instant)
      .map((part) => [part.type, part.value]),
  );
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    minutes: Number(parts.hour) * 60 + Number(parts.minute),
  };
}

const utcOf = (day: string) => Date.parse(`${day}T00:00:00.000Z`);
const dayOf = (ms: number) => new Date(ms).toISOString().slice(0, 10);

export function addDays(day: string, days: number): string {
  return dayOf(utcOf(day) + days * DAY_MS);
}

/** 요일(월=0 … 일=6, 목표의 요일과 같은 번호). */
export function weekdayOf(day: string): number {
  return (new Date(utcOf(day)).getUTCDay() + 6) % 7;
}

/** [start, end]의 날짜들. */
export function daysOf(period: Period): string[] {
  const days: string[] = [];
  for (let day = period.start; day <= period.end; day = addDays(day, 1)) {
    days.push(day);
  }
  return days;
}

const minutesOf = (time: string) =>
  Number(time.slice(0, 2)) * 60 + Number(time.slice(3, 5));

/**
 * 그 시간대의 날짜·시각(벽시계)을 UTC 시각으로. 시간대의 차이를 두 번 맞춰 서머타임 경계에서도 맞는 쪽으로 간다
 * (없는 시각 — 봄에 건너뛰는 한 시간 — 은 그 뒤로 밀린다).
 */
export function zonedToUtc(day: string, time: string, timezone: string): Date {
  const target = utcOf(day) + minutesOf(time) * 60 * 1000;
  let guess = target;
  for (let i = 0; i < 2; i++) {
    const seen = localParts(new Date(guess), timezone);
    guess += target - (utcOf(seen.date) + seen.minutes * 60 * 1000);
  }
  return new Date(guess);
}

/** 이 달의 그날(1~28). `2026-11-05`, 15 → `2026-11-15`. */
const inMonth = (day: string, dom: number) =>
  `${day.slice(0, 8)}${String(dom).padStart(2, "0")}`;

/** 그 달의 첫날. */
const firstOfMonth = (day: string) => `${day.slice(0, 8)}01`;

/** 지난달의 첫날. */
const firstOfPreviousMonth = (day: string) =>
  firstOfMonth(addDays(firstOfMonth(day), -1));

/** 보낼 날(그 시간대의 날짜)이 다루는 구간. */
export function periodFor(frequency: Frequency, sendDay: string): Period {
  if (frequency === "daily") {
    const yesterday = addDays(sendDay, -1);
    return { start: yesterday, end: yesterday };
  }
  if (frequency === "weekly") {
    // 보낼 날 이전의 가장 최근 일요일까지의 월~일(월요일에 보내면 바로 전 주)
    const end = addDays(sendDay, -(weekdayOf(sendDay) + 1));
    return { start: addDays(end, -6), end };
  }
  return {
    start: firstOfPreviousMonth(sendDay),
    end: addDays(firstOfMonth(sendDay), -1),
  };
}

/** 지금 시각 이전의 가장 최근 발송(아직 보낼 때가 안 됐으면 바로 전 발송). */
export function latestOccurrence(
  schedule: ScheduleLike,
  now: Date,
): Occurrence {
  const { date: today, minutes } = localParts(now, schedule.timezone);
  const reached = minutes >= minutesOf(schedule.send_time);
  let key: string;
  if (schedule.frequency === "daily") {
    key = reached ? today : addDays(today, -1);
  } else if (schedule.frequency === "weekly") {
    let back = (weekdayOf(today) - (schedule.weekday ?? 0) + 7) % 7;
    if (back === 0 && !reached) back = 7;
    key = addDays(today, -back);
  } else {
    const dom = schedule.day_of_month ?? 1;
    const day = Number(today.slice(8, 10));
    key =
      day > dom || (day === dom && reached)
        ? inMonth(today, dom)
        : inMonth(firstOfPreviousMonth(today), dom);
  }
  return {
    key,
    at: zonedToUtc(key, schedule.send_time, schedule.timezone),
    period: periodFor(schedule.frequency, key),
  };
}
