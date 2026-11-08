import { createAccountMenu } from "../components/account/AccountMenu";
import type { AccountStore } from "../state/accountStore";
import styles from "./NavBar.module.css";

/** 화면 맨 위 줄에 쓰는 앱 이름. */
export const APP_NAME = "whatever.log";

export interface NavBar {
  element: HTMLElement;
  /** 동기화 상태 칩을 지금 다시 읽는다. */
  refreshSyncStatus: () => Promise<void>;
  destroy: () => void;
}

export interface NavBarOptions {
  /** 계정 메뉴의 "목표 동기화"를 눌렀다. */
  onOpenSync?: () => void;
  /** 계정 메뉴의 "기기 관리"를 눌렀다. */
  onOpenDevices?: () => void;
  /** 계정 메뉴의 "계정 삭제"를 눌렀다(지울 계정의 이메일, 모르면 null). */
  onDeleteAccount?: (email: string | null, session: string | null) => void;
}

/**
 * 모든 화면 위에 한 번만 붙는 상단 막대: 왼쪽에 앱 이름, 오른쪽에 계정 영역(로그인/로그아웃).
 * 화면(레이아웃)이 바뀌어도 그대로 있고, 어느 화면이 아래에 있는지는 모른다.
 */
export function createNavBar(
  store: AccountStore,
  options: NavBarOptions = {},
): NavBar {
  const bar = document.createElement("header");
  bar.className = styles.navbar;

  const brand = document.createElement("span");
  brand.className = styles.brand;
  brand.textContent = APP_NAME;

  const account = createAccountMenu(store, options);
  bar.append(brand, account.element);

  return {
    element: bar,
    refreshSyncStatus: account.refreshSyncStatus,
    destroy: account.destroy,
  };
}
