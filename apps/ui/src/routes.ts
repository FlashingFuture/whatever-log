/**
 * 어떤 화면이 어떤 레이아웃을 쓰는지. 순수 데이터라 DOM 없이 테스트한다.
 *
 * - plain: 틀 없이 화면만(홈 — 돌아갈 곳이 없다).
 * - back: 왼쪽 위에 돌아가기 버튼이 붙는다(홈에서 들어간 하위 화면).
 *
 * 화면을 늘릴 때는 Route 종류를 더하고 여기에 레이아웃을 정한다(빠뜨리면 타입
 * 오류가 난다).
 */
import type { Route } from "./router";

export type LayoutName = "plain" | "back";

const LAYOUT_OF: Record<Route["name"], LayoutName> = {
  home: "plain",
  process: "back",
};

export function layoutOf(route: Route): LayoutName {
  return LAYOUT_OF[route.name];
}
