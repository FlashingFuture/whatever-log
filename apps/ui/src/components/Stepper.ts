import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createButton, createButtonGroup } from "./Button";

injectStyle(
  "stepper",
  `
  .stepper-label {
    text-align: center;
    font-weight: 600;
  }
  /* 누를 수 없는 라벨: 테두리는 그룹과 이어지되 버튼처럼 반응하지 않는다. */
  .button.stepper-label-static,
  .button.stepper-label-static:hover {
    background: ${theme.colors.background};
    cursor: default;
  }
  .stepper-hint {
    margin-left: 0.4rem;
    font-weight: 400;
    font-size: 0.85rem;
    color: ${theme.colors.textMuted};
  }
`,
);

export interface StepperProps {
  label: string;
  /** 라벨 옆에 작게 붙는 표시(예: "오늘"). */
  hint?: string;
  canGoPrev: boolean;
  canGoNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  /** 주면 라벨이 버튼이 된다(팝업 열기 등). 눌린 라벨 버튼을 넘긴다. */
  onLabelClick?: (labelButton: HTMLButtonElement) => void;
  /** 라벨 칸 최소 폭 — 라벨 글자 수가 바뀌어도 화살표가 덜컹거리지 않게. */
  labelMinWidth?: string;
}

/**
 * "← 라벨 →"를 테두리를 공유하는 한 덩어리로 그린다. 무엇을 넘기는지(일/주/월,
 * 연도, 달)는 모르고 라벨과 콜백만 받는다.
 */
export function createStepper(props: StepperProps): HTMLElement {
  let label: HTMLElement;
  if (props.onLabelClick) {
    const onLabelClick = props.onLabelClick;
    const button = createButton({ label: props.label, onClick: onLabelClick });
    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-expanded", "false");
    label = button;
  } else {
    label = document.createElement("span");
    label.className = "button stepper-label-static";
    label.textContent = props.label;
  }
  label.classList.add("stepper-label");
  label.style.minWidth = props.labelMinWidth ?? "14rem";

  if (props.hint) {
    const hint = document.createElement("span");
    hint.className = "stepper-hint";
    hint.textContent = props.hint;
    label.append(hint);
  }

  return createButtonGroup([
    createButton({
      label: "←",
      ariaLabel: "이전",
      disabled: !props.canGoPrev,
      onClick: props.onPrev,
    }),
    label,
    createButton({
      label: "→",
      ariaLabel: "다음",
      disabled: !props.canGoNext,
      onClick: props.onNext,
    }),
  ]);
}
