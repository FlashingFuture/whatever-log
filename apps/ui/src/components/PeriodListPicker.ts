import {
  CURRENT_PERIOD_HINT,
  formatPeriodShort,
  isCurrentPeriod,
  isSamePeriod,
  isSelectablePeriod,
  listYearOf,
  type Period,
  periodsInYear,
} from "../period";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createStepper } from "./Stepper";

injectStyle(
  "period-list-picker",
  `
  .period-list-picker {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    width: 16rem;
  }
  .period-list {
    display: flex;
    flex-direction: column;
    max-height: 18rem;
    overflow-y: auto;
  }
  .period-list-item {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    font: inherit;
    font-size: 0.9rem;
    text-align: left;
    padding: 0.4rem 0.6rem;
    border: none;
    border-radius: 6px;
    background: none;
    color: ${theme.colors.text};
    cursor: pointer;
  }
  .period-list-item:hover:not(:disabled) {
    background: ${theme.colors.track};
  }
  .period-list-item:focus-visible {
    outline: 2px solid ${theme.colors.active};
    outline-offset: -2px;
  }
  .period-list-item:disabled {
    color: ${theme.colors.textDisabled};
    cursor: default;
  }
  .period-list-item[aria-current="true"] {
    background: ${theme.colors.active};
  }
  .period-list-item-meta {
    color: ${theme.colors.textMuted};
    font-size: 0.8rem;
  }
`,
);

export interface PeriodListPickerProps {
  unit: "week" | "month";
  selected: Period;
  now: Date;
  onSelect: (period: Period) => void;
}

/**
 * 한 해의 주(또는 월)를 1월부터 아래로 늘어놓고 골라 고르는 팝업 내용. 위쪽
 * ‹ 연도 ›로 해를 넘긴다(올해보다 뒤로는 못 간다). 미래 구간은 비활성화한다.
 */
export function createPeriodListPicker(
  props: PeriodListPickerProps,
): HTMLElement {
  const root = document.createElement("div");
  root.className = "period-list-picker";
  const latestYear = props.now.getFullYear();
  let year = listYearOf(props.selected);

  function render(focusArrow?: "이전" | "다음"): void {
    const header = createStepper({
      label: `${year}년`,
      labelMinWidth: "7rem",
      canGoPrev: true,
      canGoNext: year < latestYear,
      onPrev: () => {
        year -= 1;
        render("이전");
      },
      onNext: () => {
        year += 1;
        render("다음");
      },
    });

    const list = document.createElement("div");
    list.className = "period-list";
    periodsInYear(props.unit, year).forEach((period, index) => {
      list.append(createItem(period, index));
    });
    list.addEventListener("keydown", moveFocusWithArrows);

    root.replaceChildren(header, list);
    // 해를 넘기면 헤더가 새로 그려져 포커스가 사라지므로, 누른 화살표로 돌려놓는다.
    // 최신 해에 닿아 "다음"이 꺼졌다면 항상 켜져 있는 "이전"으로 돌린다.
    if (focusArrow) {
      (
        header.querySelector<HTMLElement>(
          `[aria-label="${focusArrow}"]:not(:disabled)`,
        ) ?? header.querySelector<HTMLElement>('[aria-label="이전"]')
      )?.focus();
    }
  }

  function createItem(period: Period, index: number): HTMLButtonElement {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "period-list-item";
    item.disabled = !isSelectablePeriod(period, props.now);

    const label = document.createElement("span");
    label.textContent =
      props.unit === "week"
        ? `${index + 1}주  ${formatPeriodShort(period)}`
        : formatPeriodShort(period);
    item.append(label);

    if (isCurrentPeriod(period, props.now)) {
      const meta = document.createElement("span");
      meta.className = "period-list-item-meta";
      meta.textContent = CURRENT_PERIOD_HINT[props.unit];
      item.append(meta);
    }
    if (isSamePeriod(period, props.selected)) {
      item.setAttribute("aria-current", "true");
      item.dataset.autofocus = "center";
    }
    item.addEventListener("click", () => props.onSelect(period));
    return item;
  }

  render();
  return root;
}

/** ↑/↓로 목록 안에서 누를 수 있는 항목 사이를 옮겨 다닌다. */
function moveFocusWithArrows(event: KeyboardEvent): void {
  if (event.key !== "ArrowUp" && event.key !== "ArrowDown") {
    return;
  }
  event.preventDefault();
  const list = event.currentTarget as HTMLElement;
  const items = [
    ...list.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"),
  ];
  const current = items.indexOf(document.activeElement as HTMLButtonElement);
  const next = current + (event.key === "ArrowDown" ? 1 : -1);
  items[Math.max(0, Math.min(items.length - 1, next))]?.focus();
}
