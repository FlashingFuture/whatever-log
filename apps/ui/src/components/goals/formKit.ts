import { ApiError, type FieldError } from "../../api";
import { createButton } from "../common/Button";
import styles from "./GoalForm.module.css";

/**
 * 알림·보고서 일정 폼이 같이 쓰는 조각. 목표 폼(GoalForm)과 같은 모양·같은 스타일을 쓰고, 규칙은 서버가 검증하므로 서버가 돌려준 칸별 오류를 그
 * 칸 옆에 그대로 보여 준다(여기서 규칙을 다시 구현하지 않는다).
 */
export interface FormKit {
  form: HTMLFormElement;
  banner: HTMLElement;
  /** 칸 하나(라벨 + 입력 + 오류 자리)를 만든다. field는 서버가 오류를 알려 주는 칸 이름이다. */
  field: (field: string, label: string, control: HTMLElement) => HTMLElement;
  /** 저장·취소 버튼 줄. */
  actions: (submitLabel: string, onCancel: () => void) => HTMLElement;
  /** 저장 요청을 보낸다: 버튼을 잠그고, 실패하면 칸별 오류를 보여 주고 다시 누를 수 있게 되돌린다. */
  submit: (save: () => Promise<void>) => void;
}

export function createFormKit(idPrefix: string): FormKit {
  const form = document.createElement("form");
  form.className = styles.form;
  form.noValidate = true; // 브라우저의 검증 말풍선 대신 서버 검증 결과를 보여 준다

  const banner = document.createElement("p");
  banner.className = styles.banner;
  banner.setAttribute("role", "alert");
  banner.hidden = true;
  form.append(banner);

  const slots = new Map<string, HTMLElement>();
  let submitButton: HTMLButtonElement | null = null;
  let submitLabel = "";

  function showErrors(errors: readonly FieldError[], fallback: string): void {
    for (const slot of slots.values()) {
      slot.hidden = true;
      slot.textContent = "";
    }
    banner.hidden = true;
    const unplaced: string[] = [];
    for (const error of errors) {
      const slot = slots.get(error.field);
      if (slot) {
        slot.hidden = false;
        slot.textContent = slot.textContent
          ? `${slot.textContent} ${error.message}`
          : error.message;
      } else {
        unplaced.push(error.message);
      }
    }
    // 이 폼에 없는 칸의 오류(예: 개수 상한)나 칸 목록이 없는 오류는 맨 위에 모아 보여 준다.
    if (errors.length === 0 || unplaced.length > 0) {
      banner.hidden = false;
      banner.textContent = unplaced.length > 0 ? unplaced.join(" ") : fallback;
    }
  }

  return {
    form,
    banner,
    field(field, label, control) {
      const wrapper = document.createElement("div");
      wrapper.className = styles.field;
      const labelElement = document.createElement("label");
      labelElement.textContent = label;
      if (
        control instanceof HTMLInputElement ||
        control instanceof HTMLSelectElement
      ) {
        control.id = `${idPrefix}-${field}`;
        labelElement.htmlFor = control.id;
      }
      const error = document.createElement("p");
      error.className = styles.error;
      error.setAttribute("role", "alert");
      error.hidden = true;
      slots.set(field, error);
      wrapper.append(labelElement, control, error);
      return wrapper;
    },
    actions(label, onCancel) {
      submitLabel = label;
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.className = styles.submit;
      submit.textContent = label;
      submitButton = submit;
      const row = document.createElement("div");
      row.className = styles.actions;
      row.append(createButton({ label: "취소", onClick: onCancel }), submit);
      return row;
    },
    submit(save) {
      const button = submitButton;
      if (button) {
        button.disabled = true;
        button.textContent = "저장 중…";
      }
      save()
        .catch((error: unknown) => {
          showErrors(
            error instanceof ApiError ? error.fields : [],
            error instanceof Error ? error.message : String(error),
          );
        })
        .finally(() => {
          // 성공하면 장면이 바뀌어 이 폼은 사라진다 — 실패했을 때만 다시 눌러 볼 수 있게 되돌린다.
          if (button) {
            button.disabled = false;
            button.textContent = submitLabel;
          }
        });
    },
  };
}

/** 값 목록에서 고르는 <select>. 현재 값이 목록에 없어도(옛 값) 사라지지 않게 하나 더 보여 준다. */
export function createSelect(
  options: readonly { value: string; label: string }[],
  current: string,
  className: string,
): HTMLSelectElement {
  const select = document.createElement("select");
  select.className = className;
  for (const option of options) {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label; // 프로세스 이름 같은 값이라 textContent로만 넣는다
    select.append(element);
  }
  if (!options.some((option) => option.value === current)) {
    const stale = document.createElement("option");
    stale.value = current;
    stale.textContent = current;
    select.append(stale);
  }
  select.value = current;
  return select;
}

/** 요일 토글 버튼 줄(월=0 … 일=6). 고른 요일 집합은 돌려준 selected가 들고 있다. */
export function createWeekdayToggles(
  labels: readonly string[],
  selected: Set<number>,
): HTMLElement {
  const group = document.createElement("div");
  group.className = styles.weekdays;
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", "적용 요일");
  labels.forEach((label, day) => {
    group.append(
      createButton({
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
      }),
    );
  });
  return group;
}
