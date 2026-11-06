import type { Goal } from "../../api";
import { formatTarget, formatWeekdays } from "../../lib/goalText";
import { createIconButton } from "../common/IconButton";
import styles from "./GoalList.module.css";

export interface GoalListProps {
  goals: Goal[];
  /** 목표를 눌렀다 — 연결 프로세스 화면으로 간다. */
  onOpen: (goal: Goal) => void;
  onEdit: (goal: Goal) => void;
  onDelete: (goal: Goal) => void;
}

function describe(goal: Goal): string {
  const links = [
    goal.processes.length > 0 ? `프로세스 ${goal.processes.length}개` : "",
    goal.sites.length > 0 ? `사이트 ${goal.sites.length}개` : "",
  ].filter(Boolean);
  return [
    `하루 ${formatTarget(goal.daily_target_minutes)}`,
    formatWeekdays(goal.weekdays),
    links.length === 0 ? "연결된 프로세스 없음" : links.join(" · "),
  ].join(" · ");
}

/**
 * 목표 목록. 목표를 누르면 상세(연결 프로세스)로 간다. 수정·삭제 아이콘은 평소엔 숨겼다가 목표에
 * 마우스를 올리거나, 키보드 포커스가 들어오거나, 오른쪽 클릭하면 오른쪽 끝에 나타난다(오른쪽 클릭하면
 * 브라우저 메뉴 대신 아이콘을 고정해 두고, 다른 곳을 누르면 풀린다).
 */
export function createGoalList(props: GoalListProps): HTMLElement {
  if (props.goals.length === 0) {
    const empty = document.createElement("p");
    empty.className = styles.empty;
    empty.textContent =
      "아직 목표가 없습니다. 위의 + 버튼으로 첫 목표를 만들어 보세요.";
    return empty;
  }

  const list = document.createElement("ul");
  list.className = styles.list;
  let pinned: HTMLElement | null = null;
  const unpin = (): void => {
    pinned?.removeAttribute("data-pinned");
    pinned = null;
  };

  const outside = new AbortController();
  document.addEventListener(
    "pointerdown",
    (event) => {
      // 화면이 바뀌어 이 목록이 사라졌으면 리스너도 거둔다.
      if (!list.isConnected) {
        outside.abort();
        return;
      }
      if (pinned && !pinned.contains(event.target as Node)) {
        unpin();
      }
    },
    { capture: true, signal: outside.signal },
  );

  for (const goal of props.goals) {
    const row = document.createElement("li");
    row.className = styles.row;

    const main = document.createElement("button");
    main.type = "button";
    main.className = styles.main;
    const name = document.createElement("span");
    name.className = styles.name;
    name.textContent = goal.name; // 사용자가 쓴 글이라 textContent로만 넣는다
    const meta = document.createElement("span");
    meta.className = styles.meta;
    meta.textContent = describe(goal);
    main.append(name, meta);
    main.addEventListener("click", () => props.onOpen(goal));

    const actions = document.createElement("span");
    actions.className = styles.actions;
    actions.append(
      createIconButton({
        icon: "pencil",
        label: `${goal.name} 수정`,
        onClick: () => props.onEdit(goal),
      }),
      createIconButton({
        icon: "trash",
        label: `${goal.name} 삭제`,
        tone: "danger",
        onClick: () => props.onDelete(goal),
      }),
    );

    row.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      unpin();
      pinned = row;
      row.setAttribute("data-pinned", "true");
    });

    row.append(main, actions);
    list.append(row);
  }
  return list;
}
