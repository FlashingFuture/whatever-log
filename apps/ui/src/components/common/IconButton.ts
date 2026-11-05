import { createIcon, type IconName } from "./Icon";
import styles from "./IconButton.module.css";

export interface IconButtonProps {
  icon: IconName;
  /** 아이콘만 있는 버튼이라 뜻을 글자로 알려 줘야 한다(스크린 리더 이름이자 마우스 툴팁). */
  label: string;
  onClick: (button: HTMLButtonElement) => void;
  /** danger는 삭제처럼 되돌리기 어려운 동작에 쓴다. */
  tone?: "default" | "danger";
}

/** 아이콘 하나만 있는 작은 버튼(추가·수정·삭제·닫기 등). */
export function createIconButton(props: IconButtonProps): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className =
    props.tone === "danger"
      ? `${styles.button} ${styles.danger}`
      : styles.button;
  button.setAttribute("aria-label", props.label);
  button.title = props.label;
  button.append(createIcon(props.icon));
  button.addEventListener("click", () => props.onClick(button));
  return button;
}
