// 목표 기간(없음 / 시작일~종료일)의 화면 쪽 규칙. DOM·hub를 모르는 순수 로직(lib 층)이다. 규칙의 원본은 서버(packages/goals)이고, 여기는 글자 만들기와 상태 판정만 한다.

import { localDay } from "./goalSelection.ts";

/** 기간이 있는 목표에서 필요한 칸(둘 다 null이면 기간 없음). 날짜는 `YYYY-MM-DD`(이 PC의 로컬 날짜, 양끝 포함). */
export interface PeriodLike {
  start_date: string | null;
  end_date: string | null;
}

/**
 * 기간의 상태: none(기간 없음) / upcoming(아직 시작 전) / active(진행 중) / ended(종료됨). 날짜 글자(`YYYY-MM-DD`)는 사전순이 곧 날짜순이라
 * 시간대 계산 없이 문자열로 비교한다(오늘도 같은 형식의 로컬 날짜다).
 */
export type PeriodStatus = "none" | "upcoming" | "active" | "ended";

export function periodStatus(period: PeriodLike, today: string): PeriodStatus {
  if (period.start_date === null || period.end_date === null) {
    return "none";
  }
  if (today < period.start_date) {
    return "upcoming";
  }
  return today > period.end_date ? "ended" : "active";
}

/** 홈 캐러셀에 둘 목표인가: 종료된 목표만 뺀다(기간이 없거나, 진행 중이거나, 곧 시작할 목표는 둔다). */
export function isOnCarousel(period: PeriodLike, today: string): boolean {
  return periodStatus(period, today) !== "ended";
}

/** 오늘(이 PC의 로컬 날짜, `YYYY-MM-DD`). */
export function todayText(now: Date = new Date()): string {
  return localDay(now);
}

/** `2026-11-25` → "11월 25일"(해가 지금과 같을 때) / "2027년 1월 3일"(다를 때). 모양이 틀린 글자는 그대로 돌려준다(서버가 거르는 값이라 화면은 깨지지 않게만 한다). */
export function formatDayText(text: string, now: Date = new Date()): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (match === null) {
    return text;
  }
  const [, year, month, day] = match;
  const monthDay = `${Number(month)}월 ${Number(day)}일`;
  return Number(year) === now.getFullYear()
    ? monthDay
    : `${Number(year)}년 ${monthDay}`;
}

/** 기간의 날짜 범위만: 없으면 "기간 없음", 있으면 "11월 25일 ~ 12월 31일"(상태는 붙이지 않는다). */
export function formatPeriodRange(
  period: PeriodLike,
  now: Date = new Date(),
): string {
  if (period.start_date === null || period.end_date === null) {
    return "기간 없음";
  }
  return `${formatDayText(period.start_date, now)} ~ ${formatDayText(period.end_date, now)}`;
}

/** 기간을 한 줄로: 없으면 "기간 없음", 있으면 "11월 25일 ~ 12월 31일"에 상태("시작 전"·"종료됨")를 붙인다. */
export function describePeriod(
  period: PeriodLike,
  today: string,
  now: Date = new Date(),
): string {
  const status = periodStatus(period, today);
  if (status === "none") {
    return "기간 없음";
  }
  const range = formatPeriodRange(period, now);
  if (status === "ended") {
    return `${range} · 종료됨`;
  }
  return status === "upcoming" ? `${range} · 시작 전` : range;
}

/** 날짜(`Date`)를 `YYYY-MM-DD`로. 달력에서 고른 날을 저장하는 글자로 바꿀 때 쓴다. */
export function dayText(date: Date): string {
  return localDay(date);
}

/** `YYYY-MM-DD` → 그날 로컬 자정의 `Date`. 모양이 틀리면 null. */
export function parseDayText(text: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (match === null) {
    return null;
  }
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  );
  // 2026-02-31 같은 없는 날짜는 다른 날로 넘어가므로 되돌려 같은지 본다.
  return dayText(date) === text ? date : null;
}

/** 날짜 글자에 일 수를 더한다(예: 오늘 + 30일). 글자가 틀리면 null. */
export function addDays(text: string, days: number): string | null {
  const base = parseDayText(text);
  if (base === null) {
    return null;
  }
  return dayText(
    new Date(base.getFullYear(), base.getMonth(), base.getDate() + days),
  );
}

const WEEKDAY_SHORT = ["일", "월", "화", "수", "목", "금", "토"] as const;

/** `2026-11-25` → "2026년 11월 25일 (수)". 달력에서 고른 날을 버튼에 보일 때 쓴다. 모양이 틀린 글자는 그대로. */
export function formatFullDay(text: string): string {
  const date = parseDayText(text);
  if (date === null) {
    return text;
  }
  return `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일 (${WEEKDAY_SHORT[date.getDay()]})`;
}
