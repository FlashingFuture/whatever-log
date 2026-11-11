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
 * 홈은 15초마다 내용을 통째로 다시 그린다. 이 선택기는 그 바깥(페이지 맨 위)에 한 번만 붙여 두고 `update`로 목록만 갱신한다 — 그래야 열려 있는
 * 목록과 포커스가 갱신에 지워지지 않는다. 목록은 열 때마다 그때의 상태로 만든다.
 */
export function createGoalSelector(props: GoalSelectorProps): GoalSelector {
  let goals: readonly GoalOption[] = [];
  let selectedId: number | null = null;

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = styles.trigger;
  // 열리는 상자는 Popover가 role="dialog"로 만든다(그 안의 목록이 listbox) — 단추가 알리는 종류를 실제와 맞춘다
  trigger.setAttribute("aria-haspopup", "dialog");
  trigger.setAttribute("aria-expanded", "false");

  const name = document.createElement("span");
  name.className = styles.name;
  const caret = document.createElement("span");
  caret.className = styles.caret;
  caret.setAttribute("aria-hidden", "true");
  caret.textContent = "▾";
  trigger.append(name, caret);

  /** 지금 고른 목표(목록에 없으면 undefined — 목표 전체로 본다). */
  function selectedGoal(): GoalOption | undefined {
    return goals.find((goal) => goal.id === selectedId);
  }

  /** 단추의 글자·툴팁·스크린 리더 이름을 지금 고른 것에 맞춘다(긴 이름은 줄여 보이고 전체는 title에 둔다). */
  function renderTrigger(): void {
    const goal = selectedGoal();
    const full = goal ? goal.name : ALL_LABEL;
    name.textContent = goal ? truncateName(goal.name, MAX_NAME_CHARS) : full; // 목표 이름은 사용자 입력이라 textContent로 넣는다
    trigger.title = full;
    trigger.setAttribute("aria-label", `목표 선택: ${full}`);
  }

  /** 목록의 항목 하나. 누르면 상자를 닫고 단추로 포커스를 돌린 뒤 고른 것을 알린다. */
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

  /** 열 때마다 그때의 목록으로 만든다(목표가 바뀌었을 수 있다). */
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
