import type { Goal } from "../../api";
import { type ProcessSplit, processKey } from "../../lib/processPick";
import { createIcon } from "../common/Icon";
import styles from "./GoalProcesses.module.css";

export interface GoalProcessesProps {
  goal: Goal;
  split: ProcessSplit;
  /** 막 옮긴 프로세스 — 화면이 다시 그려진 뒤 키보드 포커스를 돌려줄 이름. */
  focusProcess?: string;
  /** 저장 중이면 옮기지 못하게 막는다. */
  busy: boolean;
  /** 프로세스를 이 목표에 연결(true)하거나 해제(false)한다. */
  onMove: (process: string, link: boolean) => void;
}

const DRAG_TYPE = "application/x-whatever-process";

/**
 * 한 목표의 프로세스 관리: 왼쪽 "연결된 프로세스", 오른쪽 "추적된 프로세스"(아직 어느 목표에도 연결되지
 * 않은 것). 항목을 누르면 반대쪽으로 옮겨지고, 끌어서 반대쪽 칸에 놓아도 옮겨진다. 다른 목표에 연결된
 * 프로세스는 어느 목표인지 함께 흐리게 보여 주고 옮길 수 없다(한 프로세스는 한 목표에만 연결된다).
 */
export function createGoalProcesses(props: GoalProcessesProps): HTMLElement {
  const root = document.createElement("div");
  root.className = styles.root;

  function item(process: string, link: boolean): HTMLLIElement {
    const li = document.createElement("li");
    li.className = styles.item;
    li.draggable = !props.busy;
    li.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData(DRAG_TYPE, process);
      event.dataTransfer?.setData("text/plain", process);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });

    const button = document.createElement("button");
    button.type = "button";
    button.className = styles.itemButton;
    button.disabled = props.busy;
    button.setAttribute(
      "aria-label",
      link ? `${process} 연결` : `${process} 연결 해제`,
    );
    button.dataset.process = process;
    const name = document.createElement("span");
    name.className = styles.itemName;
    name.title = process;
    name.textContent = process; // OS에서 온 값이라 textContent로만 넣는다
    button.append(name, createIcon(link ? "plus" : "close", 14));
    button.addEventListener("click", () => props.onMove(process, link));
    li.append(button);
    return li;
  }

  function panel(
    title: string,
    hint: string,
    items: HTMLLIElement[],
    emptyText: string,
    acceptLink: boolean,
  ): HTMLElement {
    const section = document.createElement("section");
    section.className = styles.panel;
    section.setAttribute("aria-label", title);

    const heading = document.createElement("h3");
    heading.className = styles.heading;
    heading.textContent = `${title} (${items.length})`;
    const hintElement = document.createElement("p");
    hintElement.className = styles.hint;
    hintElement.textContent = hint;

    const list = document.createElement("ul");
    list.className = styles.list;
    if (items.length === 0) {
      const empty = document.createElement("li");
      empty.className = styles.empty;
      empty.textContent = emptyText;
      list.append(empty);
    } else {
      list.append(...items);
    }

    // 놓는 자리. 이 칸에 속한 항목을 같은 칸에 놓는 건 무시하고, 반대쪽 항목만 받는다.
    list.addEventListener("dragover", (event) => {
      if (event.dataTransfer?.types.includes(DRAG_TYPE) && !props.busy) {
        event.preventDefault();
        section.setAttribute("data-over", "true");
      }
    });
    list.addEventListener("dragleave", (event) => {
      if (!list.contains(event.relatedTarget as Node | null)) {
        section.removeAttribute("data-over");
      }
    });
    list.addEventListener("drop", (event) => {
      event.preventDefault();
      section.removeAttribute("data-over");
      const process = event.dataTransfer?.getData(DRAG_TYPE);
      if (!process || props.busy) {
        return;
      }
      const alreadyHere = (
        acceptLink ? props.split.linked : props.split.available
      ).some((name) => processKey(name) === processKey(process));
      const known = [...props.split.linked, ...props.split.available].some(
        (name) => processKey(name) === processKey(process),
      );
      if (!alreadyHere && known) {
        props.onMove(process, acceptLink);
      }
    });

    section.append(heading, hintElement, list);
    return section;
  }

  const linked = panel(
    "연결된 프로세스",
    "이 목표의 수행 시간으로 세는 프로세스",
    props.split.linked.map((process) => item(process, false)),
    "연결된 프로세스가 없습니다. 오른쪽에서 눌러 추가하거나 끌어다 놓으세요.",
    true,
  );

  const availableItems = props.split.available.map((process) =>
    item(process, true),
  );
  const available = panel(
    "추적된 프로세스",
    "기록된 프로세스 중 아직 어느 목표에도 연결되지 않은 것",
    availableItems,
    "추가할 프로세스가 없습니다.",
    false,
  );

  root.append(linked, available);

  if (props.split.takenByOthers.length > 0) {
    const others = document.createElement("section");
    others.className = styles.others;
    others.setAttribute("aria-label", "다른 목표에 연결된 프로세스");
    const heading = document.createElement("h3");
    heading.className = styles.heading;
    heading.textContent = "다른 목표에 연결됨";
    const list = document.createElement("ul");
    list.className = styles.othersList;
    for (const { process, goalName } of props.split.takenByOthers) {
      const li = document.createElement("li");
      li.className = styles.otherItem;
      const name = document.createElement("span");
      name.className = styles.itemName;
      name.textContent = process;
      name.title = process;
      const owner = document.createElement("span");
      owner.className = styles.owner;
      owner.textContent = `→ ${goalName}`;
      li.append(name, owner);
      list.append(li);
    }
    others.append(heading, list);
    root.append(others);
  }

  if (props.focusProcess) {
    const target = props.focusProcess;
    queueMicrotask(() => {
      const buttons = root.querySelectorAll<HTMLButtonElement>(
        "button[data-process]",
      );
      for (const button of buttons) {
        if (processKey(button.dataset.process ?? "") === processKey(target)) {
          button.focus();
          return;
        }
      }
    });
  }
  return root;
}
