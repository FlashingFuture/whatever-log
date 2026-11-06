import type { Goal } from "../../api";
import {
  decodeTarget,
  encodeTarget,
  type LinkTarget,
  type ProcessSplit,
  processKey,
  type SiteRef,
  targetKey,
} from "../../lib/processPick";
import { createIcon } from "../common/Icon";
import styles from "./GoalProcesses.module.css";

export interface GoalProcessesProps {
  goal: Goal;
  split: ProcessSplit;
  /** 막 옮긴 대상 — 화면이 다시 그려진 뒤 키보드 포커스를 돌려줄 곳. */
  focusTarget?: LinkTarget;
  /** 저장 중이면 옮기지 못하게 막는다. */
  busy: boolean;
  /** 대상(프로세스 또는 브라우저의 사이트)을 이 목표에 연결(true)하거나 해제(false)한다. */
  onMove: (target: LinkTarget, link: boolean) => void;
}

const DRAG_TYPE = "application/x-whatever-target";

/** 다시 그리기 전후로 이어 줄 스크롤 위치: 모달 본문과 각 칸(목록)의 것. */
export interface ScrollState {
  outer: number;
  lists: Record<string, number>;
}

/** outer(스크롤되는 바깥 영역)와 그 안의 칸들의 스크롤 위치를 읽는다. */
export function readScroll(outer: HTMLElement): ScrollState {
  const lists: Record<string, number> = {};
  for (const section of outer.querySelectorAll<HTMLElement>(
    "section[aria-label]",
  )) {
    const list = section.querySelector<HTMLElement>("ul");
    if (list) {
      lists[section.getAttribute("aria-label") ?? ""] = list.scrollTop;
    }
  }
  return { outer: outer.scrollTop, lists };
}

/** readScroll로 읽어 둔 위치를 새로 그린 outer에 되돌린다(칸은 이름으로 짝을 맞춘다). */
export function restoreScroll(outer: HTMLElement, state: ScrollState): void {
  outer.scrollTop = state.outer;
  for (const section of outer.querySelectorAll<HTMLElement>(
    "section[aria-label]",
  )) {
    const top = state.lists[section.getAttribute("aria-label") ?? ""];
    const list = section.querySelector<HTMLElement>("ul");
    if (list && top !== undefined) {
      list.scrollTop = top;
    }
  }
}

/** 이 요소를 스크롤시키는 가장 가까운 조상(없으면 문서). */
function scrollParent(element: HTMLElement): HTMLElement {
  for (
    let parent = element.parentElement;
    parent;
    parent = parent.parentElement
  ) {
    const overflowY = getComputedStyle(parent).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") {
      return parent;
    }
  }
  return document.documentElement;
}

// 사이트 목록을 펼쳐 둔 브라우저(키). 한 번 옮길 때마다 화면이 다시 그려지므로, 펼친 상태는 여기서 이어 준다.
const expandedBrowsers = new Set<string>();

/**
 * 한 목표의 연결 관리: 왼쪽 "연결된 프로세스", 오른쪽 "추적된 프로세스"(아직 어느 목표에도 연결되지 않은 것).
 * 크롬·엣지 같은 브라우저는 "사이트"를 펼쳐 세부 페이지(도메인) 단위로도 고를 수 있다. 항목을 누르면 반대쪽으로
 * 옮겨지고, 끌어서 반대쪽 칸에 놓아도 옮겨진다. 다른 목표에 연결된 대상은 어느 목표인지 함께 흐리게 보여 주고
 * 옮길 수 없다(한 대상은 한 목표에만 연결된다). 브라우저 전체와 그 안의 사이트는 함께 연결할 수 없다.
 */
export function createGoalProcesses(props: GoalProcessesProps): HTMLElement {
  const root = document.createElement("div");
  root.className = styles.root;
  const { split } = props;
  // 방금 사이트를 옮겼다면 그 브라우저의 사이트 목록을 펼쳐 둔다 — 해제한 사이트가 목록에 다시 보여 포커스를
  // 돌려줄 수 있고, 이어서 같은 브라우저의 사이트를 고르기도 쉽다.
  if (props.focusTarget?.kind === "site") {
    expandedBrowsers.add(processKey(props.focusTarget.site.browser));
  }

  function itemButton(
    target: LinkTarget,
    link: boolean,
  ): { li: HTMLLIElement; button: HTMLButtonElement } {
    const li = document.createElement("li");
    li.className = styles.item;
    li.draggable = !props.busy;
    li.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData(DRAG_TYPE, encodeTarget(target));
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });

    const button = document.createElement("button");
    button.type = "button";
    button.className = styles.itemButton;
    button.disabled = props.busy;
    button.dataset.key = targetKey(target);
    const action = link ? "연결" : "연결 해제";
    const name = document.createElement("span");
    name.className = styles.itemName;
    if (target.kind === "process") {
      button.setAttribute("aria-label", `${target.process} ${action}`);
      name.title = target.process;
      name.textContent = target.process; // OS에서 온 값이라 textContent로만 넣는다
      button.append(name);
    } else {
      button.setAttribute(
        "aria-label",
        `${target.site.domain} (${target.site.browser}) ${action}`,
      );
      name.title = `${target.site.domain} · ${target.site.browser}`;
      name.textContent = target.site.domain;
      const tag = document.createElement("span");
      tag.className = styles.browserTag;
      tag.textContent = target.site.browser;
      button.append(name, tag);
    }
    button.append(createIcon(link ? "plus" : "close", 14));
    button.addEventListener("click", () => props.onMove(target, link));
    li.append(button);
    return { li, button };
  }

  const processItem = (process: string, link: boolean): HTMLLIElement =>
    itemButton({ kind: "process", process }, link).li;
  const siteItem = (site: SiteRef, link: boolean): HTMLLIElement =>
    itemButton({ kind: "site", site }, link).li;

  function isHere(target: LinkTarget, acceptLink: boolean): boolean {
    const processes = acceptLink ? split.linked : split.available;
    const sites = acceptLink ? split.linkedSites : split.availableSites;
    const keys = new Set([
      ...processes.map((process) => targetKey({ kind: "process", process })),
      ...sites.map((site) => targetKey({ kind: "site", site })),
    ]);
    return keys.has(targetKey(target));
  }

  // 놓을 수 있는 대상: 이 목표에 연결돼 있거나, 연결할 수 있는 것(둘 다 아닌 건 다른 목표 것이라 못 옮긴다).
  function isKnown(target: LinkTarget): boolean {
    return isHere(target, true) || isHere(target, false);
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
    const count = items.filter((item) => item.dataset.counted !== "no").length;
    heading.textContent = `${title} (${count})`;
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
      const target = decodeTarget(event.dataTransfer?.getData(DRAG_TYPE) ?? "");
      if (!target || props.busy) {
        return;
      }
      if (!isHere(target, acceptLink) && isKnown(target)) {
        props.onMove(target, acceptLink);
      }
    });

    section.append(heading, hintElement, list);
    return section;
  }

  // --- 왼쪽: 연결된 것(프로세스 → 사이트) ---
  const linked = panel(
    "연결된 프로세스",
    "이 목표의 수행 시간으로 세는 프로세스와 사이트",
    [
      ...split.linked.map((process) => processItem(process, false)),
      ...split.linkedSites.map((site) => siteItem(site, false)),
    ],
    "연결된 프로세스가 없습니다. 오른쪽에서 눌러 추가하거나 끌어다 놓으세요.",
    true,
  );

  // --- 오른쪽: 추가할 수 있는 프로세스(브라우저는 사이트를 펼쳐 고른다) ---
  const sitesByBrowser = new Map<string, SiteRef[]>();
  for (const site of split.availableSites) {
    const key = processKey(site.browser);
    sitesByBrowser.set(key, [...(sitesByBrowser.get(key) ?? []), site]);
  }

  function withSites(
    process: string,
    li: HTMLLIElement,
    sites: SiteRef[],
  ): HTMLLIElement[] {
    if (sites.length === 0) {
      return [li];
    }
    const key = processKey(process);
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = styles.expander;
    toggle.disabled = props.busy;
    const open = expandedBrowsers.has(key);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", `${process} 사이트`);
    toggle.textContent = `사이트 ${sites.length}개 ${open ? "▴" : "▾"}`;
    toggle.addEventListener("click", () => {
      if (expandedBrowsers.has(key)) {
        expandedBrowsers.delete(key);
      } else {
        expandedBrowsers.add(key);
      }
      // 저장할 것이 없는 화면 상태라 서버에 가지 않고 이 조각만 다시 그린다. 스크롤 위치는 이어 준다.
      const outer = scrollParent(root);
      const scroll = readScroll(outer);
      const next = createGoalProcesses(props);
      root.replaceWith(next);
      restoreScroll(outer, scroll);
      next
        .querySelector<HTMLButtonElement>(
          `button[aria-label="${process} 사이트"]`,
        )
        ?.focus({ preventScroll: true });
    });
    li.append(toggle);
    const rows = [li];
    if (open) {
      const nested = document.createElement("ul");
      nested.className = styles.nested;
      for (const site of sites) {
        const row = siteItem(site, true);
        row.dataset.counted = "no";
        nested.append(row);
      }
      const holder = document.createElement("li");
      holder.dataset.counted = "no";
      holder.append(nested);
      rows.push(holder);
    }
    return rows;
  }

  const availableItems: HTMLLIElement[] = [];
  for (const process of split.available) {
    availableItems.push(
      ...withSites(
        process,
        processItem(process, true),
        sitesByBrowser.get(processKey(process)) ?? [],
      ),
    );
  }
  // 사이트가 연결돼 있어 브라우저 전체는 못 추가하는 것: 행은 비활성으로 두고, 남은 사이트는 펼쳐 더 고를 수 있다.
  for (const { process, goalName } of split.blocked) {
    const { li, button } = itemButton({ kind: "process", process }, true);
    button.disabled = true;
    li.draggable = false;
    button.title = `${goalName} 목표에 이 브라우저의 사이트가 연결돼 있어 전체는 추가할 수 없습니다.`;
    const note = document.createElement("span");
    note.className = styles.browserTag;
    note.textContent = "사이트 연결됨";
    button.querySelector("svg")?.replaceWith(note);
    availableItems.push(
      ...withSites(process, li, sitesByBrowser.get(processKey(process)) ?? []),
    );
  }
  const available = panel(
    "추적된 프로세스",
    "기록된 프로세스 중 아직 어느 목표에도 연결되지 않은 것(브라우저는 사이트별로도 고를 수 있습니다)",
    availableItems,
    "추가할 프로세스가 없습니다.",
    false,
  );

  root.append(linked, available);

  const others = [
    ...split.takenByOthers.map(({ process, goalName }) => ({
      label: process,
      title: process,
      goalName,
    })),
    ...split.takenSitesByOthers.map(({ site, goalName }) => ({
      label: site.domain,
      title: `${site.domain} · ${site.browser}`,
      goalName,
    })),
  ];
  if (others.length > 0) {
    const section = document.createElement("section");
    section.className = styles.others;
    section.setAttribute("aria-label", "다른 목표에 연결된 프로세스");
    const heading = document.createElement("h3");
    heading.className = styles.heading;
    heading.textContent = "다른 목표에 연결됨";
    const list = document.createElement("ul");
    list.className = styles.othersList;
    for (const { label, title, goalName } of others) {
      const li = document.createElement("li");
      li.className = styles.otherItem;
      const name = document.createElement("span");
      name.className = styles.itemName;
      name.textContent = label;
      name.title = title;
      const owner = document.createElement("span");
      owner.className = styles.owner;
      owner.textContent = `→ ${goalName}`;
      li.append(name, owner);
      list.append(li);
    }
    section.append(heading, list);
    root.append(section);
  }

  const focus = props.focusTarget;
  if (focus) {
    queueMicrotask(() => {
      const wanted = targetKey(focus);
      for (const button of root.querySelectorAll<HTMLButtonElement>(
        "button[data-key]",
      )) {
        if (button.dataset.key === wanted) {
          // 포커스가 목록을 끌고 가지 않게 한다 — 옮긴 항목이 다른 칸의 낯선 자리로 가도 보던 자리를 지킨다.
          button.focus({ preventScroll: true });
          return;
        }
      }
    });
  }
  return root;
}
