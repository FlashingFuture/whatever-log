import { openExternalLink } from "../../api";
import { PRIVACY_DOC_URL } from "../../lib/links";
import type { AccountState, AccountStore } from "../../state/accountStore";
import { createButton } from "../common/Button";
import { closePopover, togglePopover } from "../common/Popover";
import styles from "./AccountMenu.module.css";

/**
 * 로그인 안내 문구. 서버로 무엇이 가고 무엇이 가지 않는지를 로그인 전에 보여 준다.
 * 실제로 나가는 값의 전체 목록은 docs/data-handling.md이고, 이 문구는 그 요약이다.
 */
const PRIVACY_SUMMARY =
  "로그인해도 목표 달성률(목표 이름·목표 시간·달성 시간)만 서버로 전달됩니다. 어떤 프로그램·사이트를 썼는지 같은 실제 사용 기록은 이 PC 밖으로 나가지 않습니다.";
const PRIVACY_FOOTNOTE =
  "계정을 구분하려고 이메일 주소가 서버에 저장됩니다. 로그인하지 않아도 기록과 목표는 그대로 사용할 수 있습니다.";

const UNAVAILABLE_TITLE: Record<"hub" | "cloud", string> = {
  hub: "로그인 상태를 확인하지 못했습니다. 잠시 뒤 다시 확인합니다.",
  cloud: "이 설치에서는 로그인 기능을 쓸 수 없습니다.",
};

export interface AccountMenu {
  element: HTMLElement;
  destroy: () => void;
}

export interface AccountMenuOptions {
  /** 로그인한 상태의 "목표 동기화" 버튼을 눌렀다 — 어떤 목표를 서버에 넘길지 고르는 창을 연다. */
  onOpenSync?: () => void;
}

/** 로그인 방식 버튼의 글자. 방식을 늘려도 "계정으로"는 어떤 이름 뒤에서든 자연스럽다. */
function providerLabel(label: string): string {
  return `${label} 계정으로 계속하기`;
}

function createPrivacyLink(): HTMLAnchorElement {
  const link = document.createElement("a");
  link.className = styles.link;
  link.href = PRIVACY_DOC_URL;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = "자세히 알아보기";
  link.addEventListener("click", (event) => {
    // 네이티브 창에서는 링크가 기본 브라우저로 열리지 않을 수 있어 hub에 열어 달라고 한다.
    // hub에 닿지 못하면 그냥 브라우저의 기본 동작(새 탭)에 맡긴다.
    event.preventDefault();
    openExternalLink("privacy").catch(() => {
      window.open(PRIVACY_DOC_URL, "_blank", "noopener,noreferrer");
    });
  });
  return link;
}

function createError(message: string): HTMLElement {
  const error = document.createElement("p");
  error.className = styles.error;
  error.setAttribute("role", "alert");
  error.textContent = message;
  return error;
}

/** 로그인 팝업의 내용. 로그인 전 안내 + 방식 버튼, 또는 로그인 진행 중 안내 + 취소. */
function renderPanel(
  panel: HTMLElement,
  state: AccountState,
  store: AccountStore,
): void {
  const title = document.createElement("h2");
  title.className = styles.panelTitle;
  title.textContent = "로그인";

  if (state.phase === "signingIn") {
    const waiting = document.createElement("p");
    waiting.textContent = "브라우저에서 로그인을 마쳐 주세요.";
    const hint = document.createElement("p");
    hint.className = styles.note;
    hint.textContent =
      "로그인 창이 보이지 않으면 열려 있는 브라우저를 확인해 주세요.";
    const cancel = createButton({
      label: "취소",
      disabled: state.busy,
      onClick: () => void store.cancelLogin(),
    });
    cancel.dataset.autofocus = "true";
    panel.replaceChildren(title, waiting, hint, cancel);
    return;
  }

  const summary = document.createElement("p");
  summary.className = styles.summary;
  summary.textContent = PRIVACY_SUMMARY;
  const footnote = document.createElement("p");
  footnote.className = styles.note;
  footnote.textContent = PRIVACY_FOOTNOTE;

  const providers = document.createElement("div");
  providers.className = styles.providers;
  providers.append(
    ...state.providers.map((provider) =>
      createButton({
        label: providerLabel(provider.label),
        disabled: state.busy,
        onClick: () => void store.login(provider.id),
      }),
    ),
  );

  panel.replaceChildren(
    title,
    summary,
    ...(state.error ? [createError(state.error)] : []),
    providers,
    footnote,
    createPrivacyLink(),
  );
}

/**
 * navbar 오른쪽의 계정 영역. 상태(AccountStore)를 보고 그리기만 하고, 로그인 규칙은 모른다.
 *
 * - 로그인 전: "로그인" 버튼 → 팝업(안내 + 로그인 방식 버튼 + 자세히 알아보기)
 * - 로그인 중: "로그인 중…" 버튼 → 팝업(브라우저에서 마쳐 달라는 안내 + 취소)
 * - 로그인 후: 이메일 + "로그아웃" 버튼
 * - 쓸 수 없을 때: 비활성 "로그인" 버튼(이유는 툴팁), 첫 확인 전에는 아무것도 그리지 않는다
 *
 * 버튼·팝업 내용은 한 번만 만들어 두고 상태가 바뀔 때 내용만 갱신한다 — 팝업이 붙잡고 있는 버튼이 중간에
 * 교체되면 열림 표시와 바깥 클릭 처리가 어긋나기 때문이다.
 */
export function createAccountMenu(
  store: AccountStore,
  options: AccountMenuOptions = {},
): AccountMenu {
  const element = document.createElement("div");
  element.className = styles.menu;

  const loginButton = createButton({
    label: "로그인",
    onClick: (button) => {
      togglePopover(button, panel, "로그인");
    },
  });
  loginButton.setAttribute("aria-haspopup", "dialog");
  loginButton.setAttribute("aria-expanded", "false");

  const panel = document.createElement("div");
  panel.className = styles.panel;

  const email = document.createElement("span");
  email.className = styles.email;
  const logoutButton = createButton({
    label: "로그아웃",
    onClick: () => void store.logout(),
  });
  const syncButton = createButton({
    label: "목표 동기화",
    onClick: () => options.onOpenSync?.(),
  });
  const logoutError = document.createElement("span");
  logoutError.className = styles.inlineError;
  logoutError.setAttribute("role", "alert");
  const signedInGroup = document.createElement("div");
  signedInGroup.className = styles.signedIn;
  signedInGroup.append(
    email,
    ...(options.onOpenSync ? [syncButton] : []),
    logoutButton,
    logoutError,
  );

  function render(state: AccountState): void {
    // 팝업 안에서 눌러 다시 그려지면 포커스가 사라진다 — 다시 그린 뒤 되돌려 놓는다.
    const hadFocus = panel.contains(document.activeElement);

    switch (state.phase) {
      case "loading":
        element.replaceChildren();
        break;
      case "unavailable":
        loginButton.disabled = true;
        loginButton.textContent = "로그인";
        loginButton.title = UNAVAILABLE_TITLE[state.reason ?? "hub"];
        element.replaceChildren(loginButton);
        break;
      case "signedOut":
      case "signingIn":
        loginButton.disabled = false;
        loginButton.title = "";
        loginButton.textContent =
          state.phase === "signingIn" ? "로그인 중…" : "로그인";
        renderPanel(panel, state, store);
        element.replaceChildren(loginButton);
        break;
      case "signedIn":
        closePopover();
        email.textContent = state.email ?? "로그인됨";
        email.title = state.email ?? "";
        logoutButton.disabled = state.busy;
        logoutError.textContent = state.error ?? "";
        element.replaceChildren(signedInGroup);
        break;
    }

    if (hadFocus) {
      panel
        .querySelector<HTMLElement>("[data-autofocus], button:not(:disabled)")
        ?.focus({ preventScroll: true });
    }
  }

  render(store.getState());
  const unsubscribe = store.subscribe(render);

  return {
    element,
    destroy() {
      unsubscribe();
      closePopover();
    },
  };
}
