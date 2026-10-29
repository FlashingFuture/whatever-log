import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createButton } from "./Button";

injectStyle(
  "period-navigator",
  `
  .period-navigator {
    display: inline-flex;
    align-items: center;
    gap: 0.75rem;
  }
  .period-navigator-label {
    min-width: 14rem;
    text-align: center;
    font-weight: 600;
  }
  .period-navigator-hint {
    margin-left: 0.4rem;
    font-weight: 400;
    font-size: 0.85rem;
    color: ${theme.colors.textMuted};
  }
`,
);

export interface PeriodNavigatorProps {
  label: string;
  /** 현재 구간일 때 라벨 옆에 붙는 표시(예: "오늘"). */
  hint?: string;
  canGoPrev: boolean;
  canGoNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

/**
 * "← 라벨 →" 형태의 구간 이동 컨트롤. 구간이 일이든 주든 월이든 상관없이
 * 라벨과 이동 가능 여부만 받아서 그린다.
 */
export function createPeriodNavigator(
  props: PeriodNavigatorProps,
): HTMLElement {
  const nav = document.createElement("div");
  nav.className = "period-navigator";

  const label = document.createElement("span");
  label.className = "period-navigator-label";
  // 라벨이 바뀔 때 스크린 리더가 새 구간을 읽어주게 한다.
  label.setAttribute("aria-live", "polite");
  label.textContent = props.label;
  if (props.hint) {
    const hint = document.createElement("span");
    hint.className = "period-navigator-hint";
    hint.textContent = props.hint;
    label.append(hint);
  }

  nav.append(
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
  );
  return nav;
}
