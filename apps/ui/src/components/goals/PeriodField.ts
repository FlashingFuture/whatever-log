import {
  addDays,
  dayText,
  formatFullDay,
  parseDayText,
  todayText,
} from "../../lib/goalPeriod";
import { periodContaining } from "../../lib/period";
import { createButton } from "../common/Button";
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
 * 목표 기간 칸: **없음 / 설정** 선택, 설정하면 시작일·종료일 두 줄이 나오고 각 줄을 누르면 그 자리에서 달력이 펼쳐진다(홈의 날짜 달력과 같은 컴포넌트).
 * 모달 안의 폼이라 달력을 팝업이 아니라 줄 아래에 **펼친다** — 팝업은 모달 뒤에 가려진다. 고를 수 있는 날은 서버 규칙을 미리 보여 주는 것이다(과거는 못 고르고,
 * 이미 저장된 값은 과거여도 그대로 둘 수 있고, 종료일은 시작일 이후). 규칙의 원본은 서버이고 틀린 값은 서버가 칸별로 알려 준다.
 */
export function createPeriodField(props: PeriodFieldProps): PeriodField {
  const today = todayText();
  const savedStart = props.start;
  const savedEnd = props.end;
  let enabled = props.start !== null && props.end !== null;
  let start = props.start ?? today;
  let end = props.end ?? addDays(today, DEFAULT_LENGTH_DAYS) ?? today;
  let openPicker: "start" | "end" | null = null;

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
          openPicker = null;
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

  /** 날짜 한 줄: 라벨 + 고른 날(누르면 달력을 펼치고 접는다) + 펼쳐진 달력. */
  function dateRow(which: "start" | "end", label: string): HTMLElement {
    const row = document.createElement("div");
    row.className = styles.row;
    const value = which === "start" ? start : end;
    const open = openPicker === which;

    const trigger = createButton({
      label: formatFullDay(value),
      onClick: () => {
        openPicker = open ? null : which;
        render();
        root.querySelector<HTMLElement>(`[data-period-${which}]`)?.focus();
      },
    });
    trigger.dataset[which === "start" ? "periodStart" : "periodEnd"] = "";
    trigger.setAttribute("aria-expanded", String(open));
    trigger.setAttribute("aria-label", `${label}: ${formatFullDay(value)}`);

    const name = document.createElement("span");
    name.className = styles.label;
    name.textContent = label;
    const line = document.createElement("div");
    line.className = styles.line;
    line.append(name, trigger);
    row.append(line);

    if (open) {
      const selected = parseDayText(value) ?? new Date();
      row.append(
        createCalendarPicker({
          selected: periodContaining("day", selected),
          now: new Date(),
          isSelectable: (day) => isSelectable(which, dayText(day.start)),
          onSelect: (day) => {
            choose(which, dayText(day.start));
            openPicker = null;
            render();
            root.querySelector<HTMLElement>(`[data-period-${which}]`)?.focus();
          },
        }),
      );
    }
    return row;
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
