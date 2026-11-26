import { createAccountMenu } from "../components/account/AccountMenu";
import { createIconButton } from "../components/common/IconButton";
import type { AccountStore } from "../state/accountStore";
import styles from "./NavBar.module.css";

/** 화면 맨 위 줄에 쓰는 앱 이름. */
export const APP_NAME = "whatever.log";

export interface NavBar {
  element: HTMLElement;
  /** 동기화 상태 칩을 지금 다시 읽는다. */
  refreshSyncStatus: () => Promise<void>;
  /** 앱 이름 왼쪽의 뒤로 가기 버튼을 보이거나 감춘다(감춰도 자리는 남아 앱 이름이 움직이지 않는다). */
  setBackVisible: (visible: boolean) => void;
  destroy: () => void;
}

export interface NavBarOptions {
  /** 뒤로 가기 버튼을 눌렀다. */
  onBack?: () => void;
  /** 계정 메뉴의 "목표 동기화"를 눌렀다. */
  onOpenSync?: () => void;
  /** 계정 메뉴의 "기기 관리"를 눌렀다(주지 않으면 그 항목이 메뉴에 없다). */
  onOpenDevices?: () => void;
  /** 계정 메뉴의 "계정 삭제"를 눌렀다(지울 계정의 이메일, 모르면 null). */
  onDeleteAccount?: (email: string | null, session: string | null) => void;
}

/**
 * 모든 화면 위에 한 번만 붙는 상단 막대: 왼쪽에 뒤로 가기 버튼과 앱 이름, 오른쪽에 계정 영역(로그인/로그아웃).
 * 화면이 바뀌어도 그대로 있고, 어느 화면이 아래에 있는지는 모른다 — 뒤로 가기를 보일지는 main이 정한다.
 */
export function createNavBar(
  store: AccountStore,
  options: NavBarOptions = {},
): NavBar {
  const bar = document.createElement("header");
  bar.className = styles.navbar;

  const back = createIconButton({
    icon: "back",
    label: "이전 화면으로 돌아가기",
    onClick: () => options.onBack?.(),
  });
  back.classList.add(styles.back);

  const brand = document.createElement("span");
  brand.className = styles.brand;
  brand.textContent = APP_NAME;

  const start = document.createElement("div");
  start.className = styles.start;
  start.append(back, brand);

  const account = createAccountMenu(store, options);
  bar.append(start, account.element);

  return {
    element: bar,
    refreshSyncStatus: account.refreshSyncStatus,
    setBackVisible(visible) {
      back.classList.toggle(styles.backHidden, !visible);
    },
    destroy: account.destroy,
  };
}
