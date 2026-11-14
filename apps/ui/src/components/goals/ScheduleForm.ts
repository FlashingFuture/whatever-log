import type { ReportSchedule, ReportScheduleInput } from "../../api";
import { WEEKDAY_LABELS } from "../../lib/goalText";
import { createFormKit, createSelect } from "./formKit";
import styles from "./GoalForm.module.css";

export interface ScheduleFormProps {
  /** 지금 저장된 일정(없으면 null — 새로 만든다). */
  schedule: ReportSchedule | null;
  onSubmit: (input: ReportScheduleInput) => Promise<void>;
  onCancel: () => void;
}

const FREQUENCIES = [
  { value: "daily", label: "매일" },
  { value: "weekly", label: "매주" },
  { value: "monthly", label: "매달" },
] as const;

/** 매달 일자는 28일까지(서버 규칙 — 29~31일은 없는 달이 있다). */
const DAYS_OF_MONTH = Array.from({ length: 28 }, (_, index) => ({
  value: String(index + 1),
  label: `${index + 1}일`,
}));

/**
 * 보고서 메일 일정 폼: 켜짐, 주기(매일·매주·매달), 요일(매주일 때) 또는 일자(매달일 때), 보낼 시각. 고른 주기에 맞지 않는 칸은 숨기고 보내지도 않는다.
 * 값의 규칙은 서버가 검증한다. 여기서 저장하는 것은 **설정**이고, 실제 메일 발송은 서버가 연결되면 붙는다.
 */
export function createScheduleForm(props: ScheduleFormProps): HTMLElement {
  const kit = createFormKit("schedule-form");
  const current = props.schedule;

  const enabled = document.createElement("input");
  enabled.type = "checkbox";
  enabled.checked = current?.enabled ?? true;
  const enabledLabel = document.createElement("label");
  enabledLabel.append(enabled, " 이 일정으로 보고서 보내기");

  const frequency = createSelect(
    FREQUENCIES,
    current?.frequency ?? "weekly",
    styles.input,
  );
  const weekday = createSelect(
    WEEKDAY_LABELS.map((label, index) => ({
      value: String(index),
      label: `${label}요일`,
    })),
    String(current?.weekday ?? 0),
    styles.input,
  );
  const dayOfMonth = createSelect(
    DAYS_OF_MONTH,
    String(current?.day_of_month ?? 1),
    styles.input,
  );
  const sendTime = document.createElement("input");
  sendTime.type = "time";
  sendTime.className = styles.input;
  sendTime.value = current?.send_time ?? "09:00";

  const weekdayField = kit.field("weekday", "요일", weekday);
  const dayField = kit.field("day_of_month", "일자", dayOfMonth);
  function syncVisibleFields(): void {
    weekdayField.hidden = frequency.value !== "weekly";
    dayField.hidden = frequency.value !== "monthly";
  }
  frequency.addEventListener("change", syncVisibleFields);
  syncVisibleFields();

  kit.form.append(
    kit.field("enabled", "켜짐", enabledLabel),
    kit.field("frequency", "주기", frequency),
    weekdayField,
    dayField,
    kit.field("send_time", "보낼 시각", sendTime),
    kit.actions("저장", props.onCancel),
  );

  kit.form.addEventListener("submit", (event) => {
    event.preventDefault();
    kit.submit(() =>
      props.onSubmit({
        enabled: enabled.checked,
        frequency: frequency.value,
        weekday: frequency.value === "weekly" ? Number(weekday.value) : null,
        day_of_month:
          frequency.value === "monthly" ? Number(dayOfMonth.value) : null,
        send_time: sendTime.value,
      }),
    );
  });
  return kit.form;
}
