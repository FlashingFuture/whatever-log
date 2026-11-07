import {
  ApiError,
  type FieldError,
  type Goal,
  type GoalInput,
} from "../../api";
import { WEEKDAY_LABELS } from "../../lib/goalText";
import { createButton } from "../common/Button";
import styles from "./GoalForm.module.css";

export interface GoalFormProps {
  /** 수정이면 그 목표, 새로 만들면 null. */
  goal: Goal | null;
  /** 폼 위에 보여 줄 안내(없으면 null). */
  notice?: string | null;
  /** 저장한다. 실패하면 거부된다(칸별 오류가 담긴 ApiError면 그 칸 옆에 보여 준다). */
  onSubmit: (input: GoalInput) => Promise<void>;
  onCancel: () => void;
}

const FORM_FIELDS = ["name", "daily_target_minutes", "weekdays"] as const;

/**
 * 목표 시간 칸의 글자를 서버에 보낼 값으로: 10진 정수로만 이뤄진 글자(앞의 0 없이)면 숫자, 아니면 글자 그대로
 * (그러면 서버가 칸별로 알려 준다). Number()는 공백·"1e2"·"0x10"도 숫자로 받아 주므로 쓰지 않는다.
 */
function minutesValue(text: string): number | string {
  return /^(0|[1-9]\d*)$/.test(text) ? Number(text) : text;
}

/**
 * 목표 만들기·수정 폼(이름, 하루 목표 시간, 적용 요일). 규칙은 서버(packages/goals)가 엄격하게 검증하므로
 * 여기서는 다시 구현하지 않고, 서버가 돌려준 칸별 오류를 그 칸 옆에 그대로 보여 준다. 이름 앞뒤 공백만
 * 입력 편의로 지우고 나머지 값은 사용자가 넣은 그대로 보낸다. 연결 프로세스·사이트는 이 폼에서 바꾸지 않는다(수정할
 * 때 기존 연결을 그대로 보낸다 — 연결은 상세 화면에서 한다).
 */
export function createGoalForm(props: GoalFormProps): HTMLElement {
  const form = document.createElement("form");
  form.className = styles.form;
  form.noValidate = true; // 브라우저의 검증 말풍선 대신 서버 검증 결과를 보여 준다

  const banner = document.createElement("p");
  banner.className = styles.banner;
  banner.setAttribute("role", "alert");
  banner.hidden = true;

  const errorSlots = new Map<string, HTMLElement>();
  function field(
    id: (typeof FORM_FIELDS)[number],
    label: string,
    control: HTMLElement,
  ): HTMLElement {
    const wrapper = document.createElement("div");
    wrapper.className = styles.field;
    const labelElement = document.createElement("label");
    labelElement.textContent = label;
    if (control instanceof HTMLInputElement) {
      control.id = `goal-form-${id}`;
      labelElement.htmlFor = control.id;
    }
    const error = document.createElement("p");
    error.className = styles.error;
    error.setAttribute("role", "alert");
    error.hidden = true;
    errorSlots.set(id, error);
    wrapper.append(labelElement, control, error);
    return wrapper;
  }

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.className = styles.input;
  nameInput.autocomplete = "off";
  nameInput.value = props.goal?.name ?? "";

  const minutesInput = document.createElement("input");
  minutesInput.type = "text";
  minutesInput.inputMode = "numeric";
  minutesInput.className = styles.input;
  minutesInput.autocomplete = "off";
  minutesInput.value = String(props.goal?.daily_target_minutes ?? 60);

  const selected = new Set<number>(
    props.goal?.weekdays ?? [0, 1, 2, 3, 4, 5, 6],
  );
  const weekdays = document.createElement("div");
  weekdays.className = styles.weekdays;
  weekdays.setAttribute("role", "group");
  weekdays.setAttribute("aria-label", "적용 요일");
  WEEKDAY_LABELS.forEach((label, day) => {
    const toggle = createButton({
      label,
      pressed: selected.has(day),
      onClick: (button) => {
        if (selected.has(day)) {
          selected.delete(day);
        } else {
          selected.add(day);
        }
        button.setAttribute("aria-pressed", String(selected.has(day)));
      },
    });
    weekdays.append(toggle);
  });

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = styles.submit;
  const submitLabel = props.goal ? "저장" : "만들기";
  submit.textContent = submitLabel;
  const actions = document.createElement("div");
  actions.className = styles.actions;
  actions.append(
    createButton({ label: "취소", onClick: () => props.onCancel() }),
    submit,
  );

  const notice = document.createElement("p");
  notice.className = styles.notice;
  notice.textContent = props.notice ?? "";
  notice.hidden = !props.notice;

  form.append(
    banner,
    notice,
    field("name", "이름", nameInput),
    field("daily_target_minutes", "하루 목표 시간(분)", minutesInput),
    field("weekdays", "적용 요일", weekdays),
    actions,
  );

  function showErrors(errors: readonly FieldError[], fallback: string): void {
    for (const slot of errorSlots.values()) {
      slot.hidden = true;
      slot.textContent = "";
    }
    banner.hidden = true;
    const unplaced: string[] = [];
    for (const error of errors) {
      const slot = errorSlots.get(error.field);
      if (slot) {
        slot.hidden = false;
        slot.textContent = slot.textContent
          ? `${slot.textContent} ${error.message}`
          : error.message;
      } else {
        unplaced.push(error.message);
      }
    }
    // 이 폼에 없는 칸의 오류(예: 목표 개수 상한)나 칸 목록이 없는 오류는 맨 위에 모아 보여 준다.
    if (errors.length === 0 || unplaced.length > 0) {
      banner.hidden = false;
      banner.textContent = unplaced.length > 0 ? unplaced.join(" ") : fallback;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = "저장 중…";
    props
      .onSubmit({
        name: nameInput.value.trim(),
        daily_target_minutes: minutesValue(minutesInput.value),
        weekdays: [...selected].sort((a, b) => a - b),
        processes: props.goal?.processes ?? [],
        sites: props.goal?.sites ?? [],
      })
      .catch((error: unknown) => {
        showErrors(
          error instanceof ApiError ? error.fields : [],
          error instanceof Error ? error.message : String(error),
        );
      })
      .finally(() => {
        // 성공하면 장면이 바뀌어 이 폼은 사라진다 — 실패했을 때만 다시 눌러 볼 수 있게 되돌린다.
        submit.disabled = false;
        submit.textContent = submitLabel;
      });
  });

  queueMicrotask(() => nameInput.focus());
  return form;
}
