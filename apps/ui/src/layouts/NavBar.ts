import { createAccountMenu } from "../components/account/AccountMenu";
import type { AccountStore } from "../state/accountStore";
import styles from "./NavBar.module.css";

/** 화면 맨 위 줄에 쓰는 앱 이름. */
export const APP_NAME = "whatever.log";

export interface NavBar {
  element: HTMLElement;
  destroy: () => void;
}

export interface NavBarOptions {
  /** 로그인한 상태의 "목표 동기화" 버튼을 눌렀다. */
  onOpenSync?: () => void;
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

  const account = createAccountMenu(store, { onOpenSync: options.onOpenSync });
  bar.append(brand, account.element);

  return { element: bar, destroy: account.destroy };
}
