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
`,
);

export interface ButtonProps {
  label: string;
  onClick: () => void;
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
  button.addEventListener("click", props.onClick);
  return button;
}
