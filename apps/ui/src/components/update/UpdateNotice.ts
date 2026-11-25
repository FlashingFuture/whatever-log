import {
  checkUpdateNow,
  fetchUpdate,
  openExternalLink,
  setUpdateEnabled,
  type UpdateState,
} from "../../api";
import {
  bannerText,
  footerText,
  shouldShowBanner,
} from "../../lib/updateNotice";
import { createButton } from "../common/Button";
import styles from "./UpdateNotice.module.css";

const DISMISSED_KEY = "whatever-log:update-dismissed";
const RELEASES_URL = "https://github.com/FlashingFuture/whatever-log/releases";
/** 창으로 돌아왔을 때 다시 묻는 간격(hub는 하루에 한 번만 GitHub에 묻는다 — 이건 hub에 묻는 간격이다). */
const REFRESH_MS = 6 * 60 * 60 * 1000;

function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISSED_KEY);
  } catch {
    return null;
  }
}

function writeDismissed(version: string): void {
  try {
    localStorage.setItem(DISMISSED_KEY, version);
  } catch {
    // 기억하지 못하면 다음에 다시 알릴 뿐이다
  }
}

function linkButton(label: string, onClick: () => void): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = styles.linkButton;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

/** 릴리스 목록을 시스템 브라우저로 연다(네이티브 창에서는 hub가 연다. hub에 닿지 못하면 브라우저의 새 탭). */
function openReleases(): void {
  openExternalLink("releases").catch(() => {
    window.open(RELEASES_URL, "_blank", "noopener,noreferrer");
  });
}

export interface UpdateNotice {
  /** 상단 막대 아래의 알림 줄(새 버전이 있을 때만 보인다). */
  banner: HTMLElement;
  /** 화면 맨 아래 줄: 버전, 지금 확인, 알림 켜고 끄기. */
  footer: HTMLElement;
}

/**
 * 새 버전 알림(docs/updates.md 1단계). 시작할 때와 창으로 돌아왔을 때(6시간에 한 번) hub에 묻는다. 새 버전이 있으면 "받기"(릴리스 페이지)·"나중에"
 * (그 버전은 다시 알리지 않음)·"알림 끄기"를 보인다. 받기·설치는 사용자가 한다 — 앱은 알리기만 한다.
 */
export function createUpdateNotice(): UpdateNotice {
  const banner = document.createElement("div");
  banner.className = styles.banner;
  banner.setAttribute("role", "status");
  banner.hidden = true;
  const footer = document.createElement("footer");
  footer.className = styles.footer;
  let state: UpdateState | null = null;
  let busy = false;
  let lastFetch = 0;

  function render(): void {
    banner.hidden = !shouldShowBanner(state, readDismissed());
    if (!banner.hidden && state?.latest) {
      const latest = state.latest.version;
      const text = document.createElement("span");
      text.className = styles.text;
      text.textContent = bannerText(state);
      banner.replaceChildren(
        text,
        createButton({ label: "받기", onClick: openReleases }),
        createButton({
          label: "나중에",
          onClick: () => {
            writeDismissed(latest);
            render();
          },
        }),
        linkButton(
          "알림 끄기",
          () => void change(() => setUpdateEnabled(false)),
        ),
      );
    } else {
      banner.replaceChildren();
    }
    if (state === null) {
      footer.replaceChildren();
      return;
    }
    const label = document.createElement("span");
    label.textContent = footerText(state);
    const parts: HTMLElement[] = [label];
    if (state.supported) {
      const toggle = state.enabled
        ? linkButton("지금 확인", () => void change(checkUpdateNow))
        : linkButton(
            "새 버전 알림 켜기",
            () => void change(() => setUpdateEnabled(true)),
          );
      toggle.disabled = busy;
      parts.push(toggle);
    }
    footer.replaceChildren(...parts);
  }

  async function change(action: () => Promise<UpdateState>): Promise<void> {
    busy = true;
    render();
    try {
      state = await action();
    } catch {
      // hub에 닿지 못했다 — 지금 보이는 것을 그대로 둔다
    }
    busy = false;
    render();
  }

  async function refresh(): Promise<void> {
    lastFetch = Date.now();
    try {
      state = await fetchUpdate();
    } catch {
      return; // hub가 아직 뜨지 않았거나(옛 hub) 닿지 못했다 — 알리지 않는다
    }
    render();
  }

  void refresh();
  window.addEventListener("focus", () => {
    if (Date.now() - lastFetch >= REFRESH_MS) void refresh();
  });
  return { banner, footer };
}
