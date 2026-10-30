import {
  calendarWeeks,
  formatPeriod,
  isCurrentPeriod,
  isSamePeriod,
  isSelectablePeriod,
  type Period,
  periodContaining,
  shiftPeriod,
  WEEKDAYS_FROM_MONDAY,
} from "../period";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createStepper } from "./Stepper";

injectStyle(
  "calendar-picker",
  `
  .calendar-picker {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.6rem;
  }
  .calendar-grid {
    display: grid;
    grid-template-columns: repeat(7, 2.2rem);
    gap: 0.15rem;
  }
  .calendar-weekday {
    text-align: center;
    font-size: 0.75rem;
    color: ${theme.colors.textMuted};
    padding-bottom: 0.2rem;
  }
  .calendar-day {
    font: inherit;
    font-size: 0.85rem;
    height: 2.2rem;
    border: 1px solid transparent;
    border-radius: 6px;
    background: none;
    color: ${theme.colors.text};
    cursor: pointer;
  }
  .calendar-day:hover:not(:disabled) {
    background: ${theme.colors.track};
  }
  .calendar-day:focus-visible {
    outline: 2px solid ${theme.colors.active};
    outline-offset: -2px;
  }
  .calendar-day.is-outside {
    color: ${theme.colors.textMuted};
  }
  .calendar-day:disabled {
    color: ${theme.colors.textDisabled};
    cursor: default;
  }
  .calendar-day[aria-current="date"] {
    border-color: ${theme.colors.border};
  }
  .calendar-day[aria-pressed="true"] {
    background: ${theme.colors.active};
  }
`,
);

export interface CalendarPickerProps {
  /** 지금 보고 있는 날(unit이 "day"인 구간). */
  selected: Period;
  now: Date;
  onSelect: (period: Period) => void;
}

const ARROW_DAY_STEPS: Record<string, number> = {
  ArrowLeft: -1,
  ArrowRight: 1,
  ArrowUp: -7,
  ArrowDown: 7,
};

/** 날짜를 고르는 달력. 위쪽 ‹ 연·월 ›로 달을 넘긴다(이번 달보다 뒤로는 못 간다). */
export function createCalendarPicker(props: CalendarPickerProps): HTMLElement {
  const root = document.createElement("div");
  root.className = "calendar-picker";
  let month = periodContaining("month", props.selected.start);

  function render(): void {
    const start = month.start;
    const header = createStepper({
      label: `${start.getFullYear()}년 ${start.getMonth() + 1}월`,
      labelMinWidth: "9rem",
      canGoPrev: true,
      canGoNext: isSelectablePeriod(shiftPeriod(month, 1), props.now),
      onPrev: () => showMonth(shiftPeriod(month, -1), "이전"),
      onNext: () => showMonth(shiftPeriod(month, 1), "다음"),
    });

    const grid = document.createElement("div");
    grid.className = "calendar-grid";
    for (const name of WEEKDAYS_FROM_MONDAY) {
      const weekday = document.createElement("span");
      weekday.className = "calendar-weekday";
      weekday.textContent = name;
      grid.append(weekday);
    }
    for (const week of calendarWeeks(start)) {
      for (const date of week) {
        grid.append(createDay(periodContaining("day", date)));
      }
    }
    grid.addEventListener("keydown", moveWithArrows);

    root.replaceChildren(header, grid);
  }

  function createDay(day: Period): HTMLButtonElement {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "calendar-day";
    button.textContent = String(day.start.getDate());
    // 칸에는 숫자만 보이니, 스크린 리더에는 날짜 전체를 읽어준다.
    button.setAttribute("aria-label", formatPeriod(day));
    button.dataset.time = String(day.start.getTime());
    button.disabled = !isSelectablePeriod(day, props.now);
    if (day.start.getMonth() !== month.start.getMonth()) {
      button.classList.add("is-outside");
    }
    if (isCurrentPeriod(day, props.now)) {
      button.setAttribute("aria-current", "date");
    }
    if (isSamePeriod(day, props.selected)) {
      button.setAttribute("aria-pressed", "true");
      button.dataset.autofocus = "";
    }
    button.addEventListener("click", () => props.onSelect(day));
    return button;
  }

  function showMonth(next: Period, focusArrow: "이전" | "다음"): void {
    month = next;
    render();
    // 달을 넘기면 헤더가 새로 그려져 포커스가 사라지므로, 누른 화살표로 돌려놓는다.
    root
      .querySelector<HTMLElement>(`[aria-label="${focusArrow}"]:not(:disabled)`)
      ?.focus();
  }

  function focusDay(day: Period): void {
    root
      .querySelector<HTMLElement>(`[data-time="${day.start.getTime()}"]`)
      ?.focus();
  }

  /** ←/→는 하루, ↑/↓는 한 주씩 옮긴다. 다른 달로 넘어가면 그 달을 그린다. */
  function moveWithArrows(event: KeyboardEvent): void {
    const step = ARROW_DAY_STEPS[event.key];
    const focused = document.activeElement as HTMLElement | null;
    if (step === undefined || !focused?.dataset.time) {
      return;
    }
    event.preventDefault();
    const from = periodContaining(
      "day",
      new Date(Number(focused.dataset.time)),
    );
    const target = shiftPeriod(from, step);
    if (!isSelectablePeriod(target, props.now)) {
      return;
    }
    if (target.start.getMonth() !== month.start.getMonth()) {
      month = periodContaining("month", target.start);
      render();
    }
    focusDay(target);
  }

  render();
  return root;
}
