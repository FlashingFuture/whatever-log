import type { MailScheduleFields } from "../../api";
import { WEEKDAY_LABELS } from "../../lib/goalText";
import type { ScheduleFieldsLike } from "../../lib/mailSubscription";
import { createFormKit, createSelect } from "./formKit";
import styles from "./GoalForm.module.css";

export interface ScheduleFormProps {
  /** 처음 값(이 목표의 구독, 없으면 이 PC에 저장해 둔 옛 일정, 없으면 기본 — lib/mailSubscription의 initialFields). */
  initial: ScheduleFieldsLike;
  /** 매일을 고를 수 있는가(무료 요금제의 매일 구독자 상한). 못 고르면 매일을 꺼 두고 이유를 보인다. */
  allowDaily: boolean;
  /** 보낼 시각의 시간대: 고칠 때는 지금 구독의 시간대, 새로 신청하면 이 PC의 시간대. */
  timezone: string;
  /** 이 PC의 시간대. timezone과 다르면 "이 PC의 시간대로 바꾸기"를 보인다(기본은 바꾸지 않음). */
  localTimezone: string;
  submitLabel: string;
  onSubmit: (fields: MailScheduleFields, timezone: string) => Promise<void>;
  onCancel: () => void;
}

/** 매달 일자는 28일까지(서버 규칙 — 29~31일은 없는 달이 있다). */
const DAYS_OF_MONTH = Array.from({ length: 28 }, (_, index) => ({
  value: String(index + 1),
  label: `${index + 1}일`,
}));

/**
 * 보고서 메일 일정 폼: 주기(매일·매주·매달), 요일(매주일 때) 또는 일자(매달일 때), 보낼 시각. 고른 주기에 맞지 않는 칸은 숨기고 보내지도 않는다.
 * 켜고 끄기는 폼 밖(구역의 버튼)에서 한다. 값의 규칙은 서버가 검증한다.
 */
export function createScheduleForm(props: ScheduleFormProps): HTMLElement {
  const kit = createFormKit("schedule-form");
  const initial = props.initial;

  const frequency = createSelect(
    [
      {
        value: "daily",
        label: props.allowDaily ? "매일" : "매일 (지금은 신청할 수 없어요)",
      },
      { value: "weekly", label: "매주" },
      { value: "monthly", label: "매달" },
    ],
    !props.allowDaily && initial.frequency === "daily"
      ? "weekly"
      : initial.frequency,
    styles.input,
  );
  const daily = frequency.querySelector<HTMLOptionElement>(
    'option[value="daily"]',
  );
  if (daily && !props.allowDaily) daily.disabled = true;

  const weekday = createSelect(
    WEEKDAY_LABELS.map((label, index) => ({
      value: String(index),
      label: `${label}요일`,
    })),
    String(initial.weekday ?? 0),
    styles.input,
  );
  const dayOfMonth = createSelect(
    DAYS_OF_MONTH,
    String(initial.day_of_month ?? 1),
    styles.input,
  );
  const sendTime = document.createElement("input");
  sendTime.type = "time";
  sendTime.className = styles.input;
  sendTime.value = initial.send_time;

  const weekdayField = kit.field("weekday", "요일", weekday);
  const dayField = kit.field("day_of_month", "일자", dayOfMonth);
  function syncVisibleFields(): void {
    weekdayField.hidden = frequency.value !== "weekly";
    dayField.hidden = frequency.value !== "monthly";
  }
  frequency.addEventListener("change", syncVisibleFields);
  syncVisibleFields();

  const zone = document.createElement("p");
  zone.className = styles.hint;
  const differs = props.timezone !== props.localTimezone;
  zone.textContent = differs
    ? `보낼 시각은 이 구독의 시간대(${props.timezone}) 기준이에요. 이 PC의 시간대(${props.localTimezone})와 달라요.`
    : `보낼 시각은 이 PC의 시간대(${props.timezone}) 기준이에요. 매일은 전날, 매주는 지난주(월~일), 매달은 지난달의 달성도를 보내요.`;
  // 다른 시간대의 PC에서 고칠 때만: 바꾸지 않는 것이 기본이다(일정을 안 바꿔도 보내는 시각·구간이 달라지므로 사용자가 고르게).
  const switchZone = document.createElement("input");
  switchZone.type = "checkbox";
  const switchLabel = document.createElement("label");
  switchLabel.className = styles.hint;
  switchLabel.append(
    switchZone,
    ` 이 PC의 시간대(${props.localTimezone})로 바꾸기`,
  );
  switchLabel.hidden = !differs;

  kit.form.append(
    kit.field("frequency", "주기", frequency),
    weekdayField,
    dayField,
    kit.field("send_time", "보낼 시각", sendTime),
    zone,
    switchLabel,
    kit.actions(props.submitLabel, props.onCancel),
  );

  kit.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const chosen = frequency.value as MailScheduleFields["frequency"];
    kit.submit(() =>
      props.onSubmit(
        {
          frequency: chosen,
          weekday: chosen === "weekly" ? Number(weekday.value) : null,
          day_of_month: chosen === "monthly" ? Number(dayOfMonth.value) : null,
          send_time: sendTime.value,
        },
        differs && switchZone.checked ? props.localTimezone : props.timezone,
      ),
    );
  });
  return kit.form;
}
