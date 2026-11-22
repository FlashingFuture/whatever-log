import {
  addDays,
  dayText,
  formatFullDay,
  parseDayText,
  todayText,
} from "../../lib/goalPeriod";
import { periodContaining } from "../../lib/period";
import { createButton } from "../common/Button";
import { closePopover, togglePopover } from "../common/Popover";
import { createCalendarPicker } from "../period/CalendarPicker";
import styles from "./PeriodField.module.css";

export interface PeriodFieldProps {
  /** 지금 저장된 기간(새 목표면 둘 다 null). 이 값과 같은 날은 과거여도 그대로 둘 수 있다(서버 규칙). */
  start: string | null;
  end: string | null;
}

export interface PeriodField {
  element: HTMLElement;
  /** 폼이 서버로 보낼 값. 기간 없음이면 둘 다 null. */
  read: () => { start: string | null; end: string | null };
}

/** 기간을 설정할 때 종료일을 처음 놓는 곳: 시작일로부터 이만큼 뒤(바꿀 수 있다). */
const DEFAULT_LENGTH_DAYS = 29;

/**
 * 목표 기간 칸: **없음 / 설정** 선택, 설정하면 시작일·종료일 두 줄이 나오고 각 날짜 버튼을 누르면 그 버튼에 붙은 달력 팝업이 열린다(홈의 날짜 달력과 같은
 * 컴포넌트·팝업). 팝업은 화면 안에 들어오게 놓인다(아래 자리가 모자라면 버튼 위로). 고를 수 있는 날은 서버 규칙을 미리 보여 주는 것이다(과거는 못 고르고,
 * 이미 저장된 값은 과거여도 그대로 둘 수 있고, 종료일은 시작일 이후). 규칙의 원본은 서버이고 틀린 값은 서버가 칸별로 알려 준다.
 */
export function createPeriodField(props: PeriodFieldProps): PeriodField {
  const today = todayText();
  const savedStart = props.start;
  const savedEnd = props.end;
  let enabled = props.start !== null && props.end !== null;
  let start = props.start ?? today;
  let end = props.end ?? addDays(today, DEFAULT_LENGTH_DAYS) ?? today;

  const root = document.createElement("div");
  root.className = styles.field;

  function render(): void {
    const toggle = document.createElement("div");
    toggle.className = styles.toggle;
    toggle.setAttribute("role", "group");
    toggle.setAttribute("aria-label", "기간");
    toggle.append(
      createButton({
        label: "없음",
        pressed: !enabled,
        onClick: () => {
          enabled = false;
          render();
        },
      }),
      createButton({
        label: "설정",
        pressed: enabled,
        onClick: () => {
          enabled = true;
          render();
        },
      }),
    );
    root.replaceChildren(toggle);
    if (!enabled) {
      return;
    }
    root.append(dateRow("start", "시작일"), dateRow("end", "종료일"));
  }

  /** 날짜 한 줄: 라벨 + 고른 날(누르면 그 버튼에 붙은 달력 팝업을 열고 닫는다). */
  function dateRow(which: "start" | "end", label: string): HTMLElement {
    const value = which === "start" ? start : end;
    const trigger = createButton({
      label: formatFullDay(value),
      onClick: () => openCalendar(trigger, which, label),
    });
    trigger.dataset[which === "start" ? "periodStart" : "periodEnd"] = "";
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-label", `${label}: ${formatFullDay(value)}`);

    const name = document.createElement("span");
    name.className = styles.label;
    name.textContent = label;
    const line = document.createElement("div");
    line.className = styles.line;
    line.append(name, trigger);
    return line;
  }

  function openCalendar(
    trigger: HTMLElement,
    which: "start" | "end",
    label: string,
  ): void {
    const value = which === "start" ? start : end;
    const calendar = createCalendarPicker({
      selected: periodContaining("day", parseDayText(value) ?? new Date()),
      now: new Date(),
      isSelectable: (day) => isSelectable(which, dayText(day.start)),
      onSelect: (day) => {
        choose(which, dayText(day.start));
        closePopover();
        // 다시 그리면 버튼이 새로 만들어지므로 새 버튼으로 포커스를 돌린다.
        render();
        root.querySelector<HTMLElement>(`[data-period-${which}]`)?.focus();
      },
    });
    togglePopover(trigger, calendar, `${label} 선택`);
  }

  /** 고를 수 있는 날: 오늘 이후(이미 저장된 값은 과거여도 그대로), 종료일은 시작일 이후. */
  function isSelectable(which: "start" | "end", day: string): boolean {
    const saved = which === "start" ? savedStart : savedEnd;
    if (day === saved) {
      return which === "start" || day >= start;
    }
    if (day < today) {
      return false;
    }
    return which === "start" || day >= start;
  }

  function choose(which: "start" | "end", day: string): void {
    if (which === "start") {
      start = day;
      if (end < start) {
        end = start; // 시작일을 종료일보다 뒤로 옮기면 종료일도 같이 옮긴다
      }
    } else {
      end = day;
    }
  }

  render();
  return {
    element: root,
    read: () => (enabled ? { start, end } : { start: null, end: null }),
  };
}
