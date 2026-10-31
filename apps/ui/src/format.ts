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
