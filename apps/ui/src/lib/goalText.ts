/** 월=0 … 일=6(파이썬 weekday()와 같다 — 서버가 쓰는 번호). */
export const WEEKDAY_LABELS = [
  "월",
  "화",
  "수",
  "목",
  "금",
  "토",
  "일",
] as const;

const WEEKDAYS = [0, 1, 2, 3, 4];
const WEEKEND = [5, 6];

/**
 * 적용 요일을 짧은 글자로: 7일이면 "매일", 월~금이면 "평일", 토·일이면 "주말", 그 밖에는 "월·수·금"처럼
 * 요일 순서대로 이어 붙인다. 중복과 순서는 정리해서 본다.
 */
export function formatWeekdays(days: readonly number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  const same = (target: number[]) =>
    sorted.length === target.length &&
    sorted.every((day, index) => day === target[index]);
  if (sorted.length === 7) {
    return "매일";
  }
  if (same(WEEKDAYS)) {
    return "평일";
  }
  if (same(WEEKEND)) {
    return "주말";
  }
  return sorted.map((day) => WEEKDAY_LABELS[day] ?? "?").join("·");
}

/** 목표 시간(분)을 사람이 읽는 글자로: 45분, 1시간, 1시간 30분. */
export function formatTarget(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) {
    return `${rest}분`;
  }
  return rest === 0 ? `${hours}시간` : `${hours}시간 ${rest}분`;
}
