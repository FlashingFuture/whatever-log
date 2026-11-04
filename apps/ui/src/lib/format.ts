/**
 * 이름이 maxChars(글자 수, 이모지 같은 보조 평면 글자도 하나)를 넘으면 앞부분만 남기고
 * "…"를 붙인다. 좁은 칸에 이름을 넣을 때 쓴다 — 전체 이름은 호출부가 따로 보여 준다.
 */
export function truncateName(name: string, maxChars: number): string {
  const chars = Array.from(name);
  return chars.length <= maxChars
    ? name
    : `${chars.slice(0, maxChars).join("")}…`;
}

/**
 * 사용 시간(초)을 사람이 읽는 글자로. 1분 미만은 초 단위로 보여 준다 — 분으로
 * 반올림하면 15초 사용이 "0분"으로 나와 막대(값이 있음)와 글자가 어긋난다.
 * 기록이 아예 없는 0초만 "0분"이다.
 */
export function formatDuration(seconds: number): string {
  if (seconds > 0 && seconds < 60) {
    return `${Math.max(1, Math.round(seconds))}초`;
  }
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours === 0 ? `${minutes}분` : `${hours}시간 ${minutes}분`;
}
