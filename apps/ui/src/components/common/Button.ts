import styles from "./Button.module.css";

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
  button.className = styles.button;
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
  group.className = styles.group;
  group.setAttribute("role", "group");
  if (ariaLabel) {
    group.setAttribute("aria-label", ariaLabel);
  }
  group.append(...buttons);
  return group;
}
