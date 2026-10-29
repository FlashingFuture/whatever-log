/**
 * 일/주/월 단위 조회 구간 계산. DOM과 무관한 순수 함수만 둔다.
 *
 * 경계는 로컬 타임존 기준이다(사용자 달력의 자정·월요일·1일). new Date(y, m, d)는
 * 로컬 자정을 만들고 일광절약시간 전환도 알아서 처리하므로, hub(Python)에서
 * 타임존을 다시 계산하지 않고 여기서 계산한 경계를 UTC로 바꿔 넘긴다.
 */

export type PeriodUnit = "day" | "week" | "month";

export interface Period {
  unit: PeriodUnit;
  /** 구간 시작(포함). */
  start: Date;
  /** 다음 구간 시작(미포함). */
  end: Date;
}

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function startOfUnit(unit: PeriodUnit, date: Date): Date {
  const y = date.getFullYear();
  const m = date.getMonth();
  const d = date.getDate();
  if (unit === "day") {
    return new Date(y, m, d);
  }
  if (unit === "week") {
    // 월요일 시작. getDay()는 일요일이 0이다.
    const daysSinceMonday = (date.getDay() + 6) % 7;
    return new Date(y, m, d - daysSinceMonday);
  }
  return new Date(y, m, 1);
}

function addUnits(unit: PeriodUnit, start: Date, count: number): Date {
  const y = start.getFullYear();
  const m = start.getMonth();
  const d = start.getDate();
  if (unit === "day") {
    return new Date(y, m, d + count);
  }
  if (unit === "week") {
    return new Date(y, m, d + 7 * count);
  }
  return new Date(y, m + count, 1);
}

export function periodContaining(unit: PeriodUnit, date: Date): Period {
  const start = startOfUnit(unit, date);
  return { unit, start, end: addUnits(unit, start, 1) };
}

export function shiftPeriod(period: Period, count: number): Period {
  const start = addUnits(period.unit, period.start, count);
  return { unit: period.unit, start, end: addUnits(period.unit, start, 1) };
}

/** 지금 시각이 들어 있는 구간인지 — 이 구간이면 "다음"으로 갈 수 없다. */
export function isCurrentPeriod(period: Period, now: Date): boolean {
  return period.start <= now && now < period.end;
}

/**
 * 단위를 바꿀 때 기준이 될 시각. 현재 구간을 보고 있었으면 지금을, 과거를
 * 보고 있었으면 그 구간의 시작을 기준으로 삼는다 — 이번 달에서 "일"로 바꾸면
 * 1일이 아니라 오늘로 가야 한다.
 */
export function anchorForUnitChange(period: Period, now: Date): Date {
  return isCurrentPeriod(period, now) ? now : period.start;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export function formatPeriod(period: Period): string {
  const { start } = period;
  if (period.unit === "day") {
    return `${start.getFullYear()}년 ${start.getMonth() + 1}월 ${start.getDate()}일 (${WEEKDAYS[start.getDay()]})`;
  }
  if (period.unit === "week") {
    const last = addUnits("day", period.end, -1);
    const lastYear =
      last.getFullYear() === start.getFullYear()
        ? ""
        : `${last.getFullYear()}.`;
    return `${start.getFullYear()}.${pad(start.getMonth() + 1)}.${pad(start.getDate())} – ${lastYear}${pad(last.getMonth() + 1)}.${pad(last.getDate())}`;
  }
  return `${start.getFullYear()}년 ${start.getMonth() + 1}월`;
}

export const CURRENT_PERIOD_HINT: Record<PeriodUnit, string> = {
  day: "오늘",
  week: "이번 주",
  month: "이번 달",
};
