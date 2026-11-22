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
} from "../../lib/period";
import { createStepper } from "../common/Stepper";
import styles from "./CalendarPicker.module.css";

export interface CalendarPickerProps {
  /** 지금 보고 있는 날(unit이 "day"인 구간). */
  selected: Period;
  now: Date;
  onSelect: (period: Period) => void;
  /**
   * 고를 수 있는 날인가. 주지 않으면 지금까지처럼 **오늘까지**만 고를 수 있다(기록을 보는 달력). 미래를 골라야 하는 달력(목표 기간의 시작일·종료일)은
   * 이 함수로 "언제부터 고를 수 있는지"를 정한다. 그러면 달을 넘기는 "다음" 단추도 제한 없이 켜 둔다.
   */
  isSelectable?: (day: Period) => boolean;
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
  root.className = styles.picker;
  let month = periodContaining("month", props.selected.start);
  const customRule = props.isSelectable !== undefined;
  const selectable = (day: Period): boolean =>
    props.isSelectable
      ? props.isSelectable(day)
      : isSelectablePeriod(day, props.now);

  function render(): void {
    const start = month.start;
    const header = createStepper({
      label: `${start.getFullYear()}년 ${start.getMonth() + 1}월`,
      labelMinWidth: "9rem",
      canGoPrev: true,
      // 기본 달력은 이번 달보다 뒤로 못 간다. 규칙을 직접 정한 달력(미래를 고르는 곳)은 달을 계속 넘길 수 있다.
      canGoNext:
        customRule || isSelectablePeriod(shiftPeriod(month, 1), props.now),
      onPrev: () => showMonth(shiftPeriod(month, -1), "이전"),
      onNext: () => showMonth(shiftPeriod(month, 1), "다음"),
    });

    const grid = document.createElement("div");
    grid.className = styles.grid;
    for (const name of WEEKDAYS_FROM_MONDAY) {
      const weekday = document.createElement("span");
      weekday.className = styles.weekday;
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
    button.className = styles.day;
    button.textContent = String(day.start.getDate());
    // 칸에는 숫자만 보이니, 스크린 리더에는 날짜 전체를 읽어준다.
    button.setAttribute("aria-label", formatPeriod(day));
    button.dataset.time = String(day.start.getTime());
    button.disabled = !selectable(day);
    if (day.start.getMonth() !== month.start.getMonth()) {
      button.classList.add(styles.outside);
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
    // 현재 달에 닿아 "다음"이 꺼졌다면 항상 켜져 있는 "이전"으로 돌린다 — 포커스가
    // body로 빠지면 팝업 안의 키보드 이동이 멈춘다.
    const target =
      root.querySelector<HTMLElement>(
        `[aria-label="${focusArrow}"]:not(:disabled)`,
      ) ?? root.querySelector<HTMLElement>('[aria-label="이전"]');
    target?.focus();
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
    if (!selectable(target)) {
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
