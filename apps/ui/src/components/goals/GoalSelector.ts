import { truncateName } from "../../lib/format";
import { closePopover, togglePopover } from "../common/Popover";
import styles from "./GoalSelector.module.css";

export interface GoalOption {
  id: number;
  name: string;
}

export interface GoalSelectorProps {
  /** 목표를 골랐다(null = 목표 전체). */
  onSelect: (id: number | null) => void;
}

export interface GoalSelector {
  element: HTMLElement;
  /** 선택 단추에 포커스가 있는가(요소를 새 내용에 옮겨 끼우면 포커스를 잃으므로, 옮기기 전에 확인해 두었다가 되돌린다). */
  hasFocus: () => boolean;
  /** 선택 단추로 포커스를 돌린다. */
  focus: () => void;
  /** 목록과 고른 것을 갱신한다. 홈이 15초마다 다시 불러올 때마다 부른다 — 선택기 자체는 갈아치워지지 않는다. */
  update: (state: {
    goals: readonly GoalOption[];
    selectedId: number | null;
  }) => void;
  destroy: () => void;
}

const ALL_LABEL = "목표 전체";
// 좁은 요약 칸에 긴 이름이 넘치지 않게 줄인다(전체 이름은 title과 목록에 있다).
const MAX_NAME_CHARS = 18;

/**
 * 홈 요약 맨 위의 목표 선택: "목표 전체" 또는 목표 하나를 고른다. 누르면 아래 삼각형(▾)이 가리키는 방향으로 목록 상자가 열린다.
 *
 * 홈은 15초마다 내용을 통째로 다시 그린다. 이 선택기는 그 바깥에서 한 번만 만들고 같은 요소를 새 내용에 끼워 넣는다 — 그래야 열려 있는
 * 목록과 포커스가 갱신에 지워지지 않는다. 목록은 열 때마다 그때의 상태로 만든다.
 */
export function createGoalSelector(props: GoalSelectorProps): GoalSelector {
  let goals: readonly GoalOption[] = [];
  let selectedId: number | null = null;

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = styles.trigger;
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");

  const name = document.createElement("span");
  name.className = styles.name;
  const caret = document.createElement("span");
  caret.className = styles.caret;
  caret.setAttribute("aria-hidden", "true");
  caret.textContent = "▾";
  trigger.append(name, caret);

  function selectedGoal(): GoalOption | undefined {
    return goals.find((goal) => goal.id === selectedId);
  }

  function renderTrigger(): void {
    const goal = selectedGoal();
    const full = goal ? goal.name : ALL_LABEL;
    name.textContent = goal ? truncateName(goal.name, MAX_NAME_CHARS) : full; // 목표 이름은 사용자 입력이라 textContent로 넣는다
    trigger.title = full;
    trigger.setAttribute("aria-label", `목표 선택: ${full}`);
  }

  function option(label: string, id: number | null): HTMLButtonElement {
    const button = document.createElement("button");
    button.type = "button";
    button.className = styles.option;
    button.setAttribute("role", "option");
    // 고른 목표가 목록에 없으면(지웠다) 목표 전체를 고른 것으로 본다 — 단추의 글자(renderTrigger)와 같은 규칙이다
    const selected = id === (selectedGoal() ? selectedId : null);
    button.setAttribute("aria-selected", String(selected));
    button.textContent = label;
    button.title = label;
    if (selected) {
      button.dataset.autofocus = "true"; // 열면 지금 고른 항목에 포커스가 간다
    }
    button.addEventListener("click", () => {
      closePopover({ restoreFocus: true });
      selectedId = id;
      renderTrigger();
      props.onSelect(id);
    });
    return button;
  }

  function buildList(): HTMLElement {
    const list = document.createElement("div");
    list.className = styles.list;
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "목표");
    list.append(
      option(ALL_LABEL, null),
      ...goals.map((goal) => option(goal.name, goal.id)),
    );
    return list;
  }

  trigger.addEventListener("click", () => {
    togglePopover(trigger, buildList(), "목표 선택");
  });
  renderTrigger();

  return {
    element: trigger,
    hasFocus: () => document.activeElement === trigger,
    focus: () => trigger.focus({ preventScroll: true }),
    update(state) {
      goals = state.goals;
      selectedId = state.selectedId;
      renderTrigger();
    },
    destroy() {
      closePopover();
    },
  };
}
