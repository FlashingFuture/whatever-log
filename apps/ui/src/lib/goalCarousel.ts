// 홈의 목표 캐러셀 순서·이동 규칙. DOM을 모르는 순수 로직(lib 층)이라 화면 없이 시험한다.
//
// 순서는 "목표 전체 → 목표 1 → 목표 2 … → 목표 N → (다시) 목표 전체"로 이어지는 원형이다. 자동으로 넘어가지 않고 사용자가 화살표·점·키보드로만 옮긴다.

import { resolveSelection } from "./goalSelection.ts";

export interface CarouselGoal {
  id: number;
  name: string;
}

/** 캐러셀의 한 칸. id가 null이면 "목표 전체"다. */
export interface CarouselItem {
  id: number | null;
  name: string;
}

export const ALL_GOALS_LABEL = "목표 전체";

/** 맨 앞에 "목표 전체"를 두고 목표들을 이어 붙인 칸 목록. */
export function carouselItems(goals: readonly CarouselGoal[]): CarouselItem[] {
  return [
    { id: null, name: ALL_GOALS_LABEL },
    ...goals.map((goal) => ({ id: goal.id, name: goal.name })),
  ];
}

/** 지금 고른 칸의 위치(0부터)와 전체 칸 수. 고른 목표가 목록에 없으면(지웠다) "목표 전체"(0번)로 본다. */
export function positionOf(
  goals: readonly CarouselGoal[],
  selectedId: number | null,
): { index: number; count: number } {
  const resolved = resolveSelection(selectedId, goals);
  const index =
    resolved === null ? 0 : goals.findIndex((goal) => goal.id === resolved) + 1;
  return { index, count: goals.length + 1 };
}

/**
 * 한 칸 앞(+1)이나 뒤(-1)로 옮긴 뒤의 선택(null = 목표 전체). 끝에서 넘기면 반대쪽 끝으로 돈다.
 * 칸이 하나뿐(목표가 없다)이면 항상 "목표 전체"다.
 */
export function stepSelection(
  goals: readonly CarouselGoal[],
  selectedId: number | null,
  delta: 1 | -1,
): number | null {
  const { index, count } = positionOf(goals, selectedId);
  const next = (index + delta + count) % count;
  return next === 0 ? null : goals[next - 1].id;
}

/** 지금 칸의 앞(왼쪽 화살표가 가는 곳)과 뒤(오른쪽 화살표가 가는 곳) 칸. 원형이라 끝에서는 반대쪽 끝이다. 칸이 하나뿐이면 둘 다 자기 자신이다. */
export function neighborsOf(
  goals: readonly CarouselGoal[],
  selectedId: number | null,
): { previous: CarouselItem; next: CarouselItem } {
  const items = carouselItems(goals);
  const { index, count } = positionOf(goals, selectedId);
  return {
    previous: items[(index - 1 + count) % count],
    next: items[(index + 1) % count],
  };
}

/** 이름의 **뒤** n글자(왼쪽 화살표 옆에 연하게 보이는 이웃 힌트). 글자 단위(이모지·한글 조합)로 센다. */
export function tailChars(text: string, count = 2): string {
  return Array.from(text).slice(-count).join("");
}

/** 이름의 **앞** n글자(오른쪽 화살표 옆에 연하게 보이는 이웃 힌트). */
export function headChars(text: string, count = 2): string {
  return Array.from(text).slice(0, count).join("");
}
