import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";

injectStyle(
  "button",
  `
  .button {
    font: inherit;
    font-size: 0.9rem;
    padding: 0.3rem 0.75rem;
    border: 1px solid ${theme.colors.border};
    border-radius: 6px;
    background: ${theme.colors.background};
    color: ${theme.colors.text};
    cursor: pointer;
  }
  .button:hover:not(:disabled) {
    background: ${theme.colors.track};
  }
  .button:disabled {
    color: ${theme.colors.textDisabled};
    cursor: default;
  }
  .button[aria-pressed="true"] {
    background: ${theme.colors.active};
    border-color: ${theme.colors.active};
  }
  .button:focus-visible {
    outline: 2px solid ${theme.colors.active};
    outline-offset: 1px;
  }

  /* 버튼 여러 개를 테두리를 공유하는 한 덩어리로 붙인다. */
  .button-group {
    display: inline-flex;
  }
  .button-group > .button {
    border-radius: 0;
  }
  .button-group > .button + .button {
    margin-left: -1px;
  }
  .button-group > .button:first-child {
    border-radius: 6px 0 0 6px;
  }
  .button-group > .button:last-child {
    border-radius: 0 6px 6px 0;
  }
  /* 겹친 테두리 중 강조된 쪽(hover/선택/포커스)이 이웃에 가려지지 않게 위로 올린다. */
  .button-group > .button:hover:not(:disabled),
  .button-group > .button:focus-visible,
  .button-group > .button[aria-pressed="true"] {
    position: relative;
    z-index: 1;
  }
`,
);

export interface ButtonProps {
  label: string;
  /** 눌린 버튼 자신을 넘긴다 — 팝업을 그 버튼 아래에 띄울 때 쓴다. */
  onClick: (button: HTMLButtonElement) => void;
  disabled?: boolean;
  /** 화살표처럼 글자만으로 뜻이 안 드러날 때 스크린 리더용 이름. */
  ariaLabel?: string;
  /** 토글/선택형 버튼의 선택 상태. 주면 aria-pressed로 나간다. */
  pressed?: boolean;
}

export function createButton(props: ButtonProps): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button";
  button.textContent = props.label;
  button.disabled = props.disabled ?? false;
  if (props.ariaLabel) {
    button.setAttribute("aria-label", props.ariaLabel);
  }
  if (props.pressed !== undefined) {
    button.setAttribute("aria-pressed", String(props.pressed));
  }
  button.addEventListener("click", () => props.onClick(button));
  return button;
}

/** 버튼들을 테두리를 공유하는 한 덩어리로 묶는다. */
export function createButtonGroup(
  buttons: HTMLElement[],
  ariaLabel?: string,
): HTMLElement {
  const group = document.createElement("div");
  group.className = "button-group";
  group.setAttribute("role", "group");
  if (ariaLabel) {
    group.setAttribute("aria-label", ariaLabel);
  }
  group.append(...buttons);
  return group;
}
