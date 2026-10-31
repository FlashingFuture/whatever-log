import { injectStyle } from "../styles/injectStyle";
import { createNavBar, type NavBar } from "./NavBar";

injectStyle(
  "app-layout",
  `
  .app-layout-nav {
    margin-bottom: 1.5rem;
  }
`,
);

export interface AppLayout {
  /** 화면(홈, 상세 …)을 갈아 끼우는 자리. */
  content: HTMLElement;
  nav: NavBar;
}

export interface AppLayoutProps {
  onHome: () => void;
  onBack: () => void;
}

/**
 * 모든 화면이 공유하는 틀: 왼쪽 위 이동 버튼 + 그 아래 화면 자리. 화면들은 이
 * 틀이 있는지 모르고 content 안에만 그린다.
 */
export function mountAppLayout(
  root: Element,
  props: AppLayoutProps,
): AppLayout {
  const nav = createNavBar(props);
  nav.element.classList.add("app-layout-nav");
  const content = document.createElement("main");
  root.replaceChildren(nav.element, content);
  return { content, nav };
}
