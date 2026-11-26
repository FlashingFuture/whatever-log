import styles from "./Toast.module.css";

// 한 번에 하나만 보인다. 새 알림이 오면 앞의 것을 바로 갈아 끼운다(쌓이지 않는다).
const SHOW_MS = 2500;

let region: HTMLElement | null = null;
let hideTimer: ReturnType<typeof setTimeout> | undefined;

/** 화면 맨 아래 가운데의 알림 자리. 처음 부를 때 한 번 만들고 계속 쓴다(스크린 리더가 바뀐 글자를 읽어 준다). */
function toastRegion(): HTMLElement {
  if (region === null || !region.isConnected) {
    region = document.createElement("div");
    region.className = styles.region;
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    document.body.append(region);
  }
  return region;
}

/**
 * 잠깐 떴다 사라지는 한 줄 알림(토스트). 사용자가 한 일이 저장됐다는 것처럼, 화면은 그대로인데 결과를 알려야 할 때 쓴다.
 * 누를 것이 없고 몇 초 뒤 저절로 사라진다 — 실패처럼 사용자가 읽고 무언가 해야 하는 내용에는 쓰지 않는다.
 */
export function showToast(message: string): void {
  const host = toastRegion();
  clearTimeout(hideTimer);
  const toast = document.createElement("div");
  toast.className = styles.toast;
  toast.textContent = message;
  host.replaceChildren(toast);
  hideTimer = setTimeout(() => host.replaceChildren(), SHOW_MS);
}
