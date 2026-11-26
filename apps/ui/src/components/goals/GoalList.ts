import type { Goal } from "../../api";
import { describePeriod, periodStatus, todayText } from "../../lib/goalPeriod";
import { formatTarget, formatWeekdays } from "../../lib/goalText";
import { createIconButton } from "../common/IconButton";
import styles from "./GoalList.module.css";

export interface GoalListProps {
  goals: Goal[];
  /** 목표를 눌렀다(관리: 연결 프로세스 화면으로, 고르기: 그 목표에 연결). */
  onOpen: (goal: Goal) => void;
  /** 주면 수정 아이콘이 생긴다. 목표를 고르기만 하는 목록(프로세스 상세의 "프로세스 연결")에서는 주지 않는다. */
  onEdit?: (goal: Goal) => void;
  /** 주면 삭제 아이콘이 생긴다. */
  onDelete?: (goal: Goal) => void;
  /** 목표마다 덧붙일 한 줄과, 누를 수 없게 할지(이미 연결됨 등). 없으면 보통의 줄이다. */
  status?: (goal: Goal) => { note: string; disabled: boolean } | null;
}

function describe(goal: Goal): string {
  const links = [
    goal.processes.length > 0 ? `프로세스 ${goal.processes.length}개` : "",
    goal.sites.length > 0 ? `사이트 ${goal.sites.length}개` : "",
  ].filter(Boolean);
  return [
    `하루 ${formatTarget(goal.daily_target_minutes)}`,
    formatWeekdays(goal.weekdays),
    // 기간이 없으면 쓰지 않는다(대부분의 목표) — 있으면 "11월 10일 ~ 11월 30일 · 종료됨"처럼.
    periodStatus(goal, todayText()) === "none"
      ? ""
      : describePeriod(goal, todayText()),
    links.length === 0 ? "연결된 프로세스 없음" : links.join(" · "),
  ]
    .filter(Boolean)
    .join(" · ");
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
    const status = props.status?.(goal) ?? null;
    if (status !== null) {
      if (status.note) {
        const note = document.createElement("span");
        note.className = styles.note;
        note.textContent = status.note;
        main.append(note);
      }
      main.disabled = status.disabled;
    }
    main.addEventListener("click", () => props.onOpen(goal));

    const actions = document.createElement("span");
    actions.className = styles.actions;
    const { onEdit, onDelete } = props;
    if (onEdit) {
      actions.append(
        createIconButton({
          icon: "pencil",
          label: `${goal.name} 수정`,
          onClick: () => onEdit(goal),
        }),
      );
    }
    if (onDelete) {
      actions.append(
        createIconButton({
          icon: "trash",
          label: `${goal.name} 삭제`,
          tone: "danger",
          onClick: () => onDelete(goal),
        }),
      );
    }

    row.append(main);
    // 아이콘이 있을 때만 오른쪽 클릭으로 고정한다(고르기만 하는 목록에서는 브라우저 메뉴를 막지 않는다).
    if (actions.childElementCount > 0) {
      row.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        unpin();
        pinned = row;
        row.setAttribute("data-pinned", "true");
      });
      row.append(actions);
    }
    list.append(row);
  }
  return list;
}
