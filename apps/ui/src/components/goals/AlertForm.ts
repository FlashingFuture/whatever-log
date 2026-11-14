import type { GoalAlert, GoalAlertInput } from "../../api";
import { integerValue } from "../../lib/goalSettings";
import { WEEKDAY_LABELS } from "../../lib/goalText";
import { createFormKit, createSelect, createWeekdayToggles } from "./formKit";
import styles from "./GoalForm.module.css";

export interface AlertFormProps {
  /** 수정이면 그 규칙, 새로 만들면 null. */
  alert: GoalAlert | null;
  /** 대상으로 고를 수 있는 프로세스들(이 목표에 연결한 것). */
  processes: readonly string[];
  onSubmit: (input: GoalAlertInput) => Promise<void>;
  onCancel: () => void;
}

const WHOLE_GOAL = "";

/**
 * 알림 규칙 만들기·수정 폼: 대상(목표 전체 또는 연결한 프로세스 하나), 마감 시각, 최소 시간(분), 적용 요일, 켜짐. "마감 시각까지 대상의 오늘 활성 시간이
 * 최소 시간에 못 미치면 알린다"는 규칙은 서버(packages/goals)가 검증하고, 틀린 칸은 그 칸 옆에 서버의 말 그대로 보인다.
 */
export function createAlertForm(props: AlertFormProps): HTMLElement {
  const kit = createFormKit("alert-form");

  const target = createSelect(
    [
      { value: WHOLE_GOAL, label: "목표 전체" },
      ...props.processes.map((name) => ({ value: name, label: name })),
    ],
    props.alert?.target_process ?? WHOLE_GOAL,
    styles.input,
  );

  const deadline = document.createElement("input");
  deadline.type = "time";
  deadline.className = styles.input;
  deadline.value = props.alert?.deadline ?? "23:00";

  const minutes = document.createElement("input");
  minutes.type = "text";
  minutes.inputMode = "numeric";
  minutes.className = styles.input;
  minutes.autocomplete = "off";
  minutes.value = String(props.alert?.min_minutes ?? 1);

  const selected = new Set<number>(
    props.alert?.weekdays ?? [0, 1, 2, 3, 4, 5, 6],
  );
  const weekdays = createWeekdayToggles(WEEKDAY_LABELS, selected);

  const enabled = document.createElement("input");
  enabled.type = "checkbox";
  enabled.checked = props.alert?.enabled ?? true;
  const enabledLabel = document.createElement("label");
  enabledLabel.append(enabled, " 이 알림 켜기");

  kit.form.append(
    kit.field("target_process", "대상", target),
    kit.field("deadline", "마감 시각", deadline),
    kit.field("min_minutes", "이 시간(분) 이상 못 하면 알림", minutes),
    kit.field("weekdays", "적용 요일", weekdays),
    kit.field("enabled", "켜짐", enabledLabel),
    kit.actions(props.alert ? "저장" : "만들기", props.onCancel),
  );

  kit.form.addEventListener("submit", (event) => {
    event.preventDefault();
    kit.submit(() =>
      props.onSubmit({
        target_process: target.value === WHOLE_GOAL ? null : target.value,
        deadline: deadline.value,
        min_minutes: integerValue(minutes.value),
        weekdays: [...selected].sort((a, b) => a - b),
        enabled: enabled.checked,
      }),
    );
  });
  return kit.form;
}
