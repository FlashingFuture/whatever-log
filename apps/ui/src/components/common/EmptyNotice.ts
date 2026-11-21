import { createButton } from "./Button";
import styles from "./EmptyNotice.module.css";

export interface EmptyNoticeProps {
  /** 비어 있는 이유와 다음에 할 일을 알리는 글. */
  text: string;
  /** 다음 단계로 이어 주는 버튼의 글자와 동작. */
  actionLabel: string;
  onAction: () => void;
}

/**
 * "아직 없어요 — 만들어 보세요" 안내와 그 일로 바로 가는 버튼. 목표가 하나도 없을 때, 목표에 연결한 프로세스가 없을 때처럼
 * 화면이 비어 있는 이유가 사용자가 할 수 있는 일일 때 쓴다(빈 화면에서 막히지 않게 다음 단계로 이어 준다).
 */
export function createEmptyNotice(props: EmptyNoticeProps): HTMLElement {
  const root = document.createElement("div");
  root.className = styles.notice;
  const text = document.createElement("p");
  text.className = styles.text;
  text.textContent = props.text;
  const action = createButton({
    label: props.actionLabel,
    onClick: () => props.onAction(),
  });
  action.dataset.emptyAction = "";
  root.append(text, action);
  return root;
}
