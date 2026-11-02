import { createButton } from "./Button";

/**
 * 돌아가기 버튼 하나. 어디로 돌아가는지는 모르고 눌렸을 때의 동작만 받는다.
 */
export function createBackBar(onBack: () => void): HTMLElement {
  const bar = document.createElement("nav");
  bar.setAttribute("aria-label", "이동");
  bar.append(
    createButton({
      label: "← 뒤로",
      ariaLabel: "이전 화면으로 돌아가기",
      onClick: onBack,
    }),
  );
  return bar;
}
