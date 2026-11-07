import {
  ApiError,
  applySync,
  fetchSyncPlan,
  openExternalLink,
  type SyncItem,
  type SyncPlan,
  type SyncResult,
} from "../../api";
import { PRIVACY_DOC_URL } from "../../lib/links";
import {
  errorLines,
  initialSelection,
  itemMeta,
  itemTag,
  mergeNote,
  moveItem,
  resultSummary,
  selectionSummary,
} from "../../lib/syncBoard";
import { createButton } from "../common/Button";
import { createIcon } from "../common/Icon";
import { createModal } from "../common/Modal";
import styles from "./SyncDialog.module.css";

export interface SyncDialogProps {
  /** 적용으로 이 PC의 목표가 바뀌었다(합치기·가져오기) — 홈의 목표 요약을 다시 불러오게 한다. */
  onGoalsChanged: () => void;
  /** 로그인이 필요한 상황(만료 등)이라는 응답을 받았다 — 계정 상태를 다시 확인하게 한다. */
  onSignedOut: () => void;
}

export interface SyncDialog {
  /**
   * 확인 창을 연다. afterLogin이면 로그인 직후의 자동 열기다: 이 계정에서 이미 확인을 마쳤거나 정할 것이 없으면
   * 창을 띄우지 않는다(매번 묻지 않는다). 직접 열면(afterLogin false) 항상 보여 준다.
   */
  open: (options: { afterLogin: boolean }) => Promise<void>;
  destroy: () => void;
}

const DRAG_TYPE = "application/x-whatever-sync-item";
const PRIVACY_TEXT =
  "서버에는 목표 이름·목표 시간·요일과 날짜별 달성 시간만 올라가요. 어떤 프로그램·사이트를 목표에 연결했는지는 이 PC에만 있고 서버로 가지 않아요.";

function paragraph(text: string, className?: string): HTMLParagraphElement {
  const element = document.createElement("p");
  element.textContent = text;
  if (className) {
    element.className = className;
  }
  return element;
}

function message(error: unknown): string {
  return error instanceof ApiError && error.message
    ? error.message
    : "처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.";
}

function privacyLink(): HTMLAnchorElement {
  const link = document.createElement("a");
  link.className = styles.link;
  link.href = PRIVACY_DOC_URL;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "자세히 알아보기";
  link.addEventListener("click", (event) => {
    // 네이티브 창에서는 링크가 기본 브라우저로 열리지 않을 수 있어 hub에 열어 달라고 한다(실패하면 기본 동작).
    event.preventDefault();
    openExternalLink("privacy").catch(() => {
      window.open(PRIVACY_DOC_URL, "_blank", "noopener,noreferrer");
    });
  });
  return link;
}

/**
 * 로그인한 뒤 "어떤 목표를 서버에 넘길까요?"를 묻는 창. 프로세스 등록 화면과 같은 두 칸 목록이다: 왼쪽은 "서버와 동기화"(선택),
 * 오른쪽은 "이 PC에만 둠". 항목을 누르면 반대쪽으로 옮겨지고 끌어 놓아도 된다. 서버에 이미 있는 목표(다른 기기에서 쓴
 * 계정)도 함께 보여 주고, 같은 이름은 "합침", 서버에만 있는 것은 "가져오기"로 구분한다.
 *
 * 올라가는 값(이름·목표 시간·요일)만 보여 주고 프로세스·사이트는 어디에도 나오지 않는다. 선택 상태는 이 창 안에서만
 * 쓰는 일시적 상태라 저장소 없이 클로저에 둔다(docs/ui-state.md).
 */
export function createSyncDialog(props: SyncDialogProps): SyncDialog {
  const modal = createModal({ label: "목표 동기화", onClose: () => {} });
  let plan: SyncPlan | null = null;
  let selection = new Set<string>();
  let busy = false;
  let result: SyncResult | null = null;
  let failure: string | null = null;
  let loadId = 0;

  function item(itemData: SyncItem, selected: boolean): HTMLLIElement {
    const li = document.createElement("li");
    li.className = styles.item;
    li.draggable = !busy;
    li.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData(DRAG_TYPE, itemData.key);
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
      }
    });

    const button = document.createElement("button");
    button.type = "button";
    button.className = styles.itemButton;
    button.disabled = busy;
    button.dataset.key = itemData.key;
    button.setAttribute(
      "aria-label",
      `${itemData.name} ${selected ? "동기화하지 않기" : "서버와 동기화"}`,
    );

    const text = document.createElement("span");
    text.className = styles.itemText;
    const name = document.createElement("span");
    name.className = styles.itemName;
    name.title = itemData.name;
    name.textContent = itemData.name; // 사용자가 쓴 글이라 textContent로만 넣는다
    const meta = document.createElement("span");
    meta.className = styles.itemMeta;
    meta.textContent = itemMeta(itemData);
    const tag = document.createElement("span");
    tag.className = styles.tag;
    tag.textContent = itemTag(itemData, selected);
    text.append(name, meta, tag);
    const note = mergeNote(itemData);
    if (note !== null && selected) {
      const noteElement = document.createElement("span");
      noteElement.className = styles.note;
      noteElement.textContent = note;
      text.append(noteElement);
    }
    button.append(text, createIcon(selected ? "close" : "plus", 14));
    button.addEventListener("click", () => move(itemData.key, !selected));
    li.append(button);
    return li;
  }

  function move(key: string, selected: boolean): void {
    if (!plan || busy) {
      return;
    }
    selection = moveItem(plan.items, selection, key, selected);
    render();
    modal.body
      .querySelector<HTMLButtonElement>(`button[data-key="${CSS.escape(key)}"]`)
      ?.focus({ preventScroll: true });
  }

  function column(
    title: string,
    hint: string,
    items: SyncItem[],
    selected: boolean,
    emptyText: string,
  ): HTMLElement {
    const section = document.createElement("section");
    section.className = styles.panel;
    section.setAttribute("aria-label", title);
    const heading = document.createElement("h3");
    heading.className = styles.heading;
    heading.textContent = `${title} (${items.length})`;
    const list = document.createElement("ul");
    list.className = styles.list;
    if (items.length === 0) {
      list.append(
        Object.assign(document.createElement("li"), {
          className: styles.empty,
          textContent: emptyText,
        }),
      );
    } else {
      list.append(...items.map((entry) => item(entry, selected)));
    }
    list.addEventListener("dragover", (event) => {
      if (event.dataTransfer?.types.includes(DRAG_TYPE) && !busy) {
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
      move(event.dataTransfer?.getData(DRAG_TYPE) ?? "", selected);
    });
    section.append(heading, paragraph(hint, styles.hint), list);
    return section;
  }

  async function submit(): Promise<void> {
    if (!plan || busy) {
      return;
    }
    busy = true;
    failure = null;
    render();
    try {
      result = await applySync([...selection], plan.email);
      if (result.merged > 0 || result.downloaded > 0) {
        props.onGoalsChanged();
      }
    } catch (error) {
      failure = message(error);
      if (error instanceof ApiError && error.status === 409) {
        props.onSignedOut();
      }
    } finally {
      busy = false;
      render();
    }
  }

  function renderBoard(current: SyncPlan): HTMLElement {
    const root = document.createElement("div");
    root.className = styles.root;
    root.append(
      paragraph(
        current.enabled
          ? "서버와 동기화할 목표를 골라 주세요."
          : "로그인했어요. 이 PC의 목표를 서버에 넘길지 골라 주세요.",
      ),
      paragraph(PRIVACY_TEXT, styles.privacy),
      privacyLink(),
    );

    const synced = current.items.filter((entry) => selection.has(entry.key));
    const local = current.items.filter((entry) => !selection.has(entry.key));
    const board = document.createElement("div");
    board.className = styles.board;
    board.append(
      column(
        "서버와 동기화",
        "서버에 올리거나 합치거나 가져올 목표",
        synced,
        true,
        "동기화할 목표가 없어요. 오른쪽에서 눌러 추가하세요.",
      ),
      column(
        "동기화하지 않음",
        "서버로 보내거나 이 PC로 가져오지 않는 목표(다시 열면 언제든 바꿀 수 있어요)",
        local,
        false,
        "모두 동기화해요.",
      ),
    );
    root.append(board);

    const summary = paragraph(
      selectionSummary(current.items, selection),
      styles.summary,
    );
    summary.setAttribute("aria-live", "polite");
    root.append(summary);
    if (failure) {
      const alert = paragraph(failure, styles.error);
      alert.setAttribute("role", "alert");
      root.append(alert);
    }

    const actions = document.createElement("div");
    actions.className = styles.actions;
    const apply = createButton({
      label: busy ? "적용하는 중…" : current.enabled ? "저장" : "동기화 시작",
      disabled: busy,
      onClick: () => void submit(),
    });
    apply.dataset.autofocus = "true";
    actions.append(
      apply,
      createButton({
        label: "나중에",
        disabled: busy,
        onClick: () => modal.close(),
      }),
    );
    root.append(actions);
    return root;
  }

  function renderResult(current: SyncPlan, done: SyncResult): HTMLElement {
    const root = document.createElement("div");
    root.className = styles.root;
    root.append(paragraph(resultSummary(done), styles.summary));
    const problems = errorLines(current.items, done);
    if (problems.length > 0) {
      const list = document.createElement("ul");
      list.className = styles.errors;
      for (const line of problems) {
        list.append(
          Object.assign(document.createElement("li"), { textContent: line }),
        );
      }
      root.append(paragraph("올리지 못한 목표가 있어요.", styles.error), list);
    }
    const close = createButton({ label: "닫기", onClick: () => modal.close() });
    close.dataset.autofocus = "true";
    root.append(
      paragraph(
        "이 PC에서 바꾸는 목표와 날짜별 달성 시간은 동기화 에이전트가 실행 중일 때 서버에 반영돼요.",
        styles.note,
      ),
      close,
    );
    return root;
  }

  function render(): void {
    const content = document.createElement("div");
    if (!plan) {
      content.append(paragraph(failure ?? "불러오는 중…"));
      if (failure) {
        content.append(
          createButton({
            label: "다시 시도",
            // 응답을 받으면 화면을 다시 그린다(성공하면 계획이, 또 실패하면 새 오류가 보인다).
            onClick: () => void load(false).then(render),
          }),
        );
      }
    } else if (result) {
      content.append(renderResult(plan, result));
    } else {
      content.append(renderBoard(plan));
    }
    modal.show({ title: "목표 동기화", content });
    content.querySelector<HTMLElement>("[data-autofocus]")?.focus({
      preventScroll: true,
    });
  }

  /** 계획을 불러온다. 가장 최근 호출의 응답만 반영한다(창을 연달아 열어도 낡은 응답이 덮지 않게). */
  async function load(auto: boolean): Promise<boolean> {
    const id = ++loadId;
    failure = null;
    try {
      const loaded = await fetchSyncPlan();
      if (id !== loadId) {
        return false;
      }
      plan = loaded;
      selection = initialSelection(loaded.items);
      result = null;
      return true;
    } catch (error) {
      if (id !== loadId) {
        return false;
      }
      plan = null;
      failure = message(error);
      if (error instanceof ApiError && error.status === 409) {
        props.onSignedOut();
      }
      // 자동 열기에서 서버에 닿지 못하면 조용히 넘어간다(로그인은 성공했다 — "목표 동기화" 버튼으로 나중에 열 수 있다).
      return !auto;
    }
  }

  return {
    async open({ afterLogin }) {
      // 적용을 보낸 채 창을 닫았다가 다시 연 경우: 새 계획을 받지 않고 진행 중인 화면을 그대로 보여 준다. 새로 받으면
      // 적용 버튼이 다시 살아나 같은 선택을 두 번 보내거나, 먼저 보낸 적용의 결과가 새 계획 화면을 덮을 수 있다.
      if (busy) {
        render();
        modal.open();
        return;
      }
      const shown = await load(afterLogin);
      if (!shown) {
        return;
      }
      if (afterLogin && plan && (plan.enabled || plan.items.length === 0)) {
        return; // 이 계정에서 이미 확인했거나 정할 것이 없다
      }
      render();
      modal.open();
    },
    destroy: () => modal.destroy(),
  };
}
