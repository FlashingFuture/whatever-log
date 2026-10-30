import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";

injectStyle(
  "popover",
  `
  .popover {
    position: absolute;
    z-index: 10;
    padding: 0.75rem;
    background: ${theme.colors.background};
    border: 1px solid ${theme.colors.border};
    border-radius: 8px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
  }
`,
);

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

/**
 * anchor 아래에 content를 띄운다. 같은 anchor로 다시 부르면 닫는다(토글).
 * 바깥을 누르거나 Esc를 누르면 닫힌다.
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
  popover.className = "popover";
  popover.setAttribute("role", "dialog");
  popover.setAttribute("aria-label", ariaLabel);
  popover.append(content);
  document.body.append(popover);
  placeBelow(popover, anchor);
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

  function onResize(): void {
    placeBelow(popover, anchor);
  }

  function close({ restoreFocus = false }: CloseOptions = {}): void {
    if (active?.element !== popover) {
      return;
    }
    active = null;
    document.removeEventListener("pointerdown", onPointerDown, true);
    document.removeEventListener("keydown", onKeyDown, true);
    window.removeEventListener("resize", onResize);
    popover.remove();
    anchor.setAttribute("aria-expanded", "false");
    if (restoreFocus && anchor.isConnected) {
      anchor.focus();
    }
  }

  document.addEventListener("pointerdown", onPointerDown, true);
  document.addEventListener("keydown", onKeyDown, true);
  window.addEventListener("resize", onResize);
  active = { anchor, element: popover, close };

  focusInitial(popover);
}

function placeBelow(popover: HTMLElement, anchor: HTMLElement): void {
  const rect = anchor.getBoundingClientRect();
  const margin = 8;
  const viewportRight = window.scrollX + document.documentElement.clientWidth;
  // anchor 가운데 아래에 두되, 화면 밖으로 나가면 안쪽으로 밀어 넣는다.
  const centered =
    rect.left + window.scrollX + rect.width / 2 - popover.offsetWidth / 2;
  const left = Math.max(
    window.scrollX + margin,
    Math.min(centered, viewportRight - popover.offsetWidth - margin),
  );
  popover.style.left = `${left}px`;
  popover.style.top = `${rect.bottom + window.scrollY + 4}px`;
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
