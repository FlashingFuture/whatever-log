import type { LayoutName } from "../routes";
import { createBackBar } from "./BackBar";
import styles from "./Layouts.module.css";

export interface LayoutProps {
  onBack: () => void;
}

/**
 * 레이아웃 이름 → 틀을 root에 그리고, 화면이 들어갈 자리(content)를 돌려준다.
 * 화면은 자기가 어떤 틀 안에 있는지 모르고 content 안에만 그린다.
 */
const LAYOUTS: Record<
  LayoutName,
  (root: Element, props: LayoutProps) => HTMLElement
> = {
  plain(root) {
    const content = document.createElement("main");
    root.replaceChildren(content);
    return content;
  },
  back(root, props) {
    const bar = createBackBar(props.onBack);
    bar.classList.add(styles.backBar);
    const content = document.createElement("main");
    root.replaceChildren(bar, content);
    return content;
  },
};

export function mountLayout(
  root: Element,
  name: LayoutName,
  props: LayoutProps,
): HTMLElement {
  return LAYOUTS[name](root, props);
}
