/**
 * 화면마다 상단 막대의 뒤로 가기 버튼을 보일지. 순수 데이터라 DOM 없이 테스트한다.
 *
 * 홈은 돌아갈 곳이 없어 감추고, 홈에서 들어간 하위 화면은 보인다. 하위 화면을 바로 열었거나 새로 고침해서 앱 안의
 * 기록이 없어도 보인다 — 그때 누르면 홈으로 간다(router의 goBack).
 *
 * 화면을 늘릴 때는 Route 종류를 더하고 여기에 정한다(빠뜨리면 타입 오류가 난다).
 */
import type { Route } from "./router";

const HAS_BACK: Record<Route["name"], boolean> = {
  home: false,
  process: true,
  goal: true,
};

export function hasBack(route: Route): boolean {
  return HAS_BACK[route.name];
}
