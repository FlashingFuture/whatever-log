import styles from "./Popover.module.css";

interface ActivePopover {
  anchor: HTMLElement;
  element: HTMLElement;
  close: (options?: CloseOptions) => void;
}

interface CloseOptions {
  /** 닫은 뒤 포커스를 팝업을 연 버튼으로 돌려놓을지. */
  restoreFocus?: boolean;
}

// 팝업은 한 번에 하나만 연다.
let active: ActivePopover | null = null;

export function isPopoverOpen(): boolean {
  return active !== null;
}

export function closePopover(options?: CloseOptions): void {
  active?.close(options);
}

/** anchor가 연 팝업일 때만 닫는다(다른 버튼이 연 팝업은 그대로 둔다). */
export function closePopoverFor(
  anchor: HTMLElement,
  options?: CloseOptions,
): void {
  if (active?.anchor === anchor) {
    active.close(options);
  }
}

/** container 안에 붙은 팝업을 닫는다(모달이 장면을 바꿀 때 — anchor가 사라진 팝업이 새 장면 위에 남지 않게). */
export function closePopoverWithin(container: Node): void {
  if (active && container.contains(active.element)) {
    active.close();
  }
}

/**
 * anchor 아래에 content를 띄운다. 같은 anchor로 다시 부르면 닫는다(토글).
 * 바깥을 누르거나 Esc를 누르면 닫힌다.
 *
 * anchor가 열린 모달(<dialog>) 안에 있으면 팝업도 그 dialog 안에 붙인다 — 모달은 top layer라 body에 붙인 팝업은
 * 그 뒤에 가려지고 포커스도 모달 밖으로 나갈 수 없다. 위치는 화면(viewport) 기준이라 어느 쪽에 붙든 같다.
 *
 * 처음 포커스는 content 안의 [data-autofocus] 요소로 간다(없으면 첫 번째로 누를
 * 수 있는 버튼). data-autofocus="center"면 스크롤 목록 가운데로 끌어온다 — 긴
 * 목록을 열었을 때 선택된 항목이 바로 보이게.
 */
export function togglePopover(
  anchor: HTMLElement,
  content: HTMLElement,
  ariaLabel: string,
): void {
  if (active?.anchor === anchor) {
    active.close({ restoreFocus: true });
    return;
  }
  closePopover();

  const popover = document.createElement("div");
  popover.className = styles.popover;
  popover.setAttribute("role", "dialog");
  popover.setAttribute("aria-label", ariaLabel);
  popover.append(content);
  const owner = anchor.closest("dialog[open]");
  (owner ?? document.body).append(popover);
  place(popover, anchor);
  anchor.setAttribute("aria-expanded", "true");

  function onPointerDown(event: PointerEvent): void {
    const target = event.target as Node;
    // anchor를 누른 경우는 anchor의 click이 토글로 처리한다.
    if (!popover.contains(target) && !anchor.contains(target)) {
      close();
    }
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      close({ restoreFocus: true });
    }
  }

  // 창 크기가 바뀌거나 anchor를 품은 영역(모달 본문 등)이 스크롤되면 따라 움직인다.
  function onReposition(): void {
    place(popover, anchor);
  }

  // 팝업을 품은 모달이 (닫기 버튼 등으로) 닫히면 팝업과 전역 리스너도 함께 정리한다 — 다시 열었을 때 옛 팝업이 남아 있지 않게.
  function onOwnerClose(): void {
    close();
  }

  function close({ restoreFocus = false }: CloseOptions = {}): void {
    if (active?.element !== popover) {
      return;
    }
    active = null;
    document.removeEventListener("pointerdown", onPointerDown, true);
    document.removeEventListener("keydown", onKeyDown, true);
    window.removeEventListener("resize", onReposition);
    document.removeEventListener("scroll", onReposition, true);
    owner?.removeEventListener("close", onOwnerClose);
    popover.remove();
    anchor.setAttribute("aria-expanded", "false");
    if (restoreFocus && anchor.isConnected) {
      anchor.focus();
    }
  }

  document.addEventListener("pointerdown", onPointerDown, true);
  document.addEventListener("keydown", onKeyDown, true);
  window.addEventListener("resize", onReposition);
  document.addEventListener("scroll", onReposition, true);
  owner?.addEventListener("close", onOwnerClose);
  active = { anchor, element: popover, close };

  focusInitial(popover);
}

/**
 * 팝업을 화면 안에 놓는다(위치는 viewport 기준, position: fixed). anchor 가운데 아래가 기본이고, 아래에 자리가 모자라고
 * 위가 더 넓으면 anchor 위로 뒤집는다. 좌우·위아래 모두 화면 가장자리에서 margin만큼 안쪽으로 밀어 넣는다.
 */
function place(popover: HTMLElement, anchor: HTMLElement): void {
  const rect = anchor.getBoundingClientRect();
  const margin = 8;
  const gap = 4;
  const viewportWidth = document.documentElement.clientWidth;
  const viewportHeight = document.documentElement.clientHeight;
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;

  const centered = rect.left + rect.width / 2 - width / 2;
  const left = Math.max(
    margin,
    Math.min(centered, viewportWidth - width - margin),
  );

  const below = rect.bottom + gap;
  const spaceBelow = viewportHeight - below - margin;
  const spaceAbove = rect.top - gap - margin;
  const top =
    height > spaceBelow && spaceAbove > spaceBelow
      ? rect.top - gap - height
      : below;
  popover.style.left = `${left}px`;
  popover.style.top = `${Math.max(margin, Math.min(top, viewportHeight - height - margin))}px`;
}

function focusInitial(popover: HTMLElement): void {
  const target =
    popover.querySelector<HTMLElement>("[data-autofocus]") ??
    popover.querySelector<HTMLElement>("button:not(:disabled)");
  if (!target) {
    return;
  }
  target.focus({ preventScroll: true });
  if (target.dataset.autofocus === "center") {
    centerInScrollParent(target, popover);
  }
}

/**
 * target을 감싼 스크롤 영역(팝업 안의 목록) 안에서만 가운데로 끌어온다.
 * scrollIntoView()는 창까지 포함한 모든 스크롤 조상을 움직여서, 창이 작으면
 * 페이지 전체가 튀어 팝업 머리글이 화면 밖으로 밀려난다.
 */
function centerInScrollParent(target: HTMLElement, popover: HTMLElement): void {
  for (
    let el = target.parentElement;
    el && el !== popover.parentElement;
    el = el.parentElement
  ) {
    if (el.scrollHeight > el.clientHeight) {
      const targetTop =
        target.getBoundingClientRect().top - el.getBoundingClientRect().top;
      el.scrollTop += targetTop - el.clientHeight / 2 + target.offsetHeight / 2;
      return;
    }
  }
}
