import { createButton, createButtonGroup } from "./Button";

export interface NavBarProps {
  onHome: () => void;
  onBack: () => void;
}

export interface NavBarState {
  /** 지금 홈이 아니어야 홈 버튼이 눌린다. */
  canGoHome: boolean;
  canGoBack: boolean;
}

export interface NavBar {
  element: HTMLElement;
  update: (state: NavBarState) => void;
}

/**
 * 왼쪽 위에 붙는 "홈 / 돌아가기" 버튼 묶음. 화면이 무엇인지는 모르고, 눌렸을 때의
 * 동작(onHome/onBack)과 누를 수 있는지(update)만 바깥에서 받는다.
 */
export function createNavBar(props: NavBarProps): NavBar {
  const element = document.createElement("nav");
  element.setAttribute("aria-label", "이동");

  const home = createButton({ label: "홈", onClick: props.onHome });
  const back = createButton({
    label: "← 뒤로",
    ariaLabel: "이전 화면으로 돌아가기",
    onClick: props.onBack,
  });
  element.append(createButtonGroup([home, back]));

  return {
    element,
    update(state) {
      home.disabled = !state.canGoHome;
      back.disabled = !state.canGoBack;
    },
  };
}
