// 홈 요약의 목표 선택(목표 전체 / 목표 하나)과 "전체 | 현 기기" 시간. DOM·hub를 모르는 순수 로직(lib 층).

/** hub가 알려 주는 모든 기기 합계의 상태(`GET /api/goals/all-devices`). local은 받을 수 없는 상태라 이 PC의 값이 곧 전체다. */
export interface GoalTotalsLike {
  state: "local" | "synced" | "unavailable";
  goals: readonly { id: number; minutes: number }[];
}

export interface GoalLike {
  id: number;
  name: string;
  active_seconds: number;
}

/** 요약에 보일 "전체 | 현 기기" 시간(초). total이 null이면 전체를 알 수 없다("-"로 보인다). */
export interface TimePair {
  total: number | null;
  device: number;
}

/** 로컬 날짜를 `YYYY-MM-DD`로(UTC로 바꾸지 않는다 — 구간은 사용자의 달력 날짜 기준이다). */
export function localDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/**
 * 구간(시작 포함, 끝 미포함)을 hub가 받는 날짜 범위(끝날 포함)로. 끝은 "다음 구간의 시작"이라 하루 전이 마지막 날이다 —
 * 그대로 쓰면 다음 구간의 첫날 기록이 합계에 섞인다. 일광절약시간으로 하루가 23·25시간이어도 날짜 연산이라 맞다.
 */
export function dayRange(start: Date, end: Date): { from: string; to: string } {
  const last = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 1);
  return { from: localDay(start), to: localDay(last < start ? start : last) };
}

/** 고른 목표가 지금 목록에 있으면 그 id, 없으면(지웠다) null = 목표 전체. */
export function resolveSelection(
  selectedId: number | null,
  goals: readonly { id: number }[],
): number | null {
  return selectedId !== null && goals.some((goal) => goal.id === selectedId)
    ? selectedId
    : null;
}

/**
 * 한 목표의 전체 시간(초). 서버 합계(분)는 이 PC가 마지막으로 올린 값을 포함하는데 에이전트가 5분마다 올리므로 이 PC의 실시간 값보다
 * 늦을 수 있다 — 그래서 둘 중 큰 값을 쓴다(전체가 현 기기보다 작게 보이지 않게). 서버에 연결되지 않은 목표(합계 없음)는 이 PC의 값이 전체다.
 */
export function goalTotalSeconds(
  localSeconds: number,
  serverMinutes: number | undefined,
): number {
  return serverMinutes === undefined
    ? localSeconds
    : Math.max(localSeconds, serverMinutes * 60);
}

/**
 * 요약의 시간 한 쌍. selectedId가 null이면 모든 목표의 합, 아니면 그 목표 하나.
 * - totals가 null이거나 unavailable: 전체를 알 수 없다(현 기기만 보인다).
 * - local: 다른 기기의 기록을 받을 수 없는 상태 — 이 PC의 값이 전체다.
 * - synced: 서버 합계와 이 PC의 값 중 큰 쪽(목표별로 따진 뒤 더한다).
 */
export function timePair(
  goals: readonly GoalLike[],
  selectedId: number | null,
  totals: GoalTotalsLike | null,
): TimePair {
  const picked =
    selectedId === null
      ? goals
      : goals.filter((goal) => goal.id === selectedId);
  const device = picked.reduce((sum, goal) => sum + goal.active_seconds, 0);
  if (totals === null || totals.state === "unavailable") {
    return { total: null, device };
  }
  if (totals.state === "local") {
    return { total: device, device };
  }
  const minutes = new Map(totals.goals.map((item) => [item.id, item.minutes]));
  const total = picked.reduce(
    (sum, goal) =>
      sum + goalTotalSeconds(goal.active_seconds, minutes.get(goal.id)),
    0,
  );
  return { total, device };
}
