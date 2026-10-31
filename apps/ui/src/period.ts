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

/** 아직 시작하지 않은(미래) 구간은 고를 수 없다 — → 버튼을 막는 것과 같은 규칙. */
export function isSelectablePeriod(period: Period, now: Date): boolean {
  return period.start <= now;
}

export function isSamePeriod(a: Period, b: Period): boolean {
  return a.unit === b.unit && a.start.getTime() === b.start.getTime();
}

/**
 * year에 걸친 모든 구간(주/월)을 순서대로 돌려준다. 주 단위는 1월 1일이 들어
 * 있는 주부터 시작하므로, 1월 1일이 월요일이 아니면 첫 주는 전년도 12월에
 * 시작한다(같은 이유로 마지막 주는 다음 해 1월로 넘어갈 수 있다).
 */
export function periodsInYear(unit: "week" | "month", year: number): Period[] {
  const nextYearStart = new Date(year + 1, 0, 1);
  const periods: Period[] = [];
  let period = periodContaining(unit, new Date(year, 0, 1));
  while (period.start < nextYearStart) {
    periods.push(period);
    period = shiftPeriod(period, 1);
  }
  return periods;
}

/**
 * 달력 한 장(monthStart가 속한 달)을 주 단위 행으로 돌려준다. 각 행은 월요일부터
 * 일요일까지 7일이고, 첫 행·마지막 행에는 앞뒤 달의 날짜가 섞인다.
 */
export function calendarWeeks(monthStart: Date): Date[][] {
  const month = periodContaining("month", monthStart);
  const weeks: Date[][] = [];
  let week = periodContaining("week", month.start);
  while (week.start < month.end) {
    const days: Date[] = [];
    for (let i = 0; i < 7; i++) {
      days.push(addUnits("day", week.start, i));
    }
    weeks.push(days);
    week = shiftPeriod(week, 1);
  }
  return weeks;
}

/** 월요일 시작 순서의 요일 이름(달력 머리글용). */
export const WEEKDAYS_FROM_MONDAY = ["월", "화", "수", "목", "금", "토", "일"];

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

/**
 * 연도(달력이면 연·월)가 이미 머리글에 있는 목록에서 쓰는 짧은 라벨.
 * 일: "29", 주: "12.29 – 01.04", 월: "1월".
 */
export function formatPeriodShort(period: Period): string {
  const { start } = period;
  if (period.unit === "day") {
    return String(start.getDate());
  }
  if (period.unit === "week") {
    const last = addUnits("day", period.end, -1);
    return `${pad(start.getMonth() + 1)}.${pad(start.getDate())} – ${pad(last.getMonth() + 1)}.${pad(last.getDate())}`;
  }
  return `${start.getMonth() + 1}월`;
}

/**
 * 목록 팝업을 열 때 어느 해의 목록을 보여줄지. 연말·연초에 걸친 주는 두 해의
 * 목록에 다 들어 있는데(periodsInYear 참고), "1월 1일이 든 주는 새해 목록의 첫
 * 줄"이라는 규칙에 맞춰 주의 마지막 날이 속한 해로 정한다.
 */
export function listYearOf(period: Period): number {
  if (period.unit !== "week") {
    return period.start.getFullYear();
  }
  return addUnits("day", period.end, -1).getFullYear();
}

export const CURRENT_PERIOD_HINT: Record<PeriodUnit, string> = {
  day: "오늘",
  week: "이번 주",
  month: "이번 달",
};

/** 구간을 잘게 나눈 한 칸(시간 하나, 날짜 하나). */
export interface Bucket {
  start: Date;
  end: Date;
}

const HOUR_MS = 60 * 60 * 1000;

/**
 * 상세 화면이 막대를 한 줄씩 그릴 칸들. 일 → 시간별, 주/월 → 날짜별.
 *
 * 하루는 일광절약시간 전환일에 23/25시간이라 "0~23시"를 가정하지 않고, 시작에서
 * 실제 1시간씩 더해 구간 끝까지 간다. 날짜별은 로컬 달력으로 하루씩 넘긴다.
 */
export function bucketsOf(period: Period): Bucket[] {
  const buckets: Bucket[] = [];
  if (period.unit === "day") {
    for (
      let start = period.start.getTime();
      start < period.end.getTime();
      start += HOUR_MS
    ) {
      const end = Math.min(start + HOUR_MS, period.end.getTime());
      buckets.push({ start: new Date(start), end: new Date(end) });
    }
    return buckets;
  }
  for (
    let day = periodContaining("day", period.start);
    day.start < period.end;
    day = shiftPeriod(day, 1)
  ) {
    buckets.push({ start: day.start, end: day.end });
  }
  return buckets;
}

/** 칸 하나의 라벨. 일: "13시", 주/월: "10/29 (목)". */
export function formatBucketLabel(unit: PeriodUnit, bucket: Bucket): string {
  const { start } = bucket;
  if (unit === "day") {
    return `${start.getHours()}시`;
  }
  return `${start.getMonth() + 1}/${start.getDate()} (${WEEKDAYS[start.getDay()]})`;
}
