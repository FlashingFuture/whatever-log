import {
  checkUpdateNow,
  dismissUpdate,
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

const RELEASES_URL = "https://github.com/FlashingFuture/whatever-log/releases";
/** 창으로 돌아왔을 때 다시 묻는 간격(조회에 성공한 뒤). hub는 하루에 한 번만 GitHub에 묻는다 — 이건 hub에 묻는 간격이다. */
const REFRESH_MS = 6 * 60 * 60 * 1000;
/** 조회에 실패했을 때(hub가 아직 뜨지 않음 등) 다시 묻는 간격: 30초부터 두 배씩, 최대 10분. */
const RETRY_FIRST_MS = 30 * 1000;
const RETRY_MAX_MS = 10 * 60 * 1000;

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
 * 새 버전 알림(docs/updates.md 1단계). 시작할 때와 창으로 돌아왔을 때(성공 뒤 6시간에 한 번) hub에 묻는다. 새 버전이 있으면 "받기"(릴리스 페이지)·
 * "나중에"(그 버전은 다시 알리지 않음 — hub가 기억한다)·"알림 끄기"를 보인다. 받기·설치는 사용자가 한다 — 앱은 알리기만 한다.
 */
export function createUpdateNotice(): UpdateNotice {
  const banner = document.createElement("div");
  banner.className = styles.banner;
  banner.setAttribute("role", "status");
  banner.hidden = true;
  const footer = document.createElement("footer");
  footer.className = styles.footer;
  let state: UpdateState | null = null;
  // "나중에"를 hub에 저장하지 못했을 때도 이 창에서는 바로 숨긴다(다시 열면 hub의 값을 따른다).
  let dismissedHere: string | null = null;
  let busy = false;
  let lastSuccess = 0;
  let retryMs = RETRY_FIRST_MS;
  let retryTimer: number | undefined;
  // 설정을 바꿀 때마다 올리는 순번. 그 전에 시작한 조회의 응답이 늦게 와도 바뀐 설정(최종 상태)을 덮지 않게 한다.
  let generation = 0;

  function dismissed(): string | null {
    return dismissedHere ?? state?.dismissed ?? null;
  }

  function render(): void {
    banner.hidden = !shouldShowBanner(state, dismissed());
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
            dismissedHere = latest;
            render();
            void change(() => dismissUpdate(latest));
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
      // 켜고 끄기는 항상 보인다(새 버전이 없을 때도 끌 수 있게). 켜져 있으면 "지금 확인"도.
      if (state.enabled) {
        parts.push(linkButton("지금 확인", () => void change(checkUpdateNow)));
      }
      parts.push(
        linkButton(
          state.enabled ? "알림 끄기" : "새 버전 알림 켜기",
          () => void change(() => setUpdateEnabled(!state?.enabled)),
        ),
      );
      for (const button of parts.slice(1)) {
        (button as HTMLButtonElement).disabled = busy;
      }
    }
    footer.replaceChildren(...parts);
  }

  async function change(action: () => Promise<UpdateState>): Promise<void> {
    generation++;
    busy = true;
    render();
    try {
      state = await action();
      dismissedHere = null; // hub가 기억한 값을 따른다
    } catch {
      // hub에 닿지 못했거나 저장하지 못했다 — 지금 보이는 것을 그대로 둔다("나중에"는 이 창에서만 숨긴 채로)
    }
    busy = false;
    render();
  }

  async function refresh(): Promise<void> {
    window.clearTimeout(retryTimer);
    const started = generation;
    let next: UpdateState;
    try {
      next = await fetchUpdate();
    } catch {
      // hub가 아직 뜨지 않았거나 닿지 못했다 — 짧게 기다렸다 다시 묻는다(성공할 때까지 간격을 늘린다).
      retryTimer = window.setTimeout(() => void refresh(), retryMs);
      retryMs = Math.min(retryMs * 2, RETRY_MAX_MS);
      return;
    }
    lastSuccess = Date.now();
    retryMs = RETRY_FIRST_MS;
    if (started !== generation) {
      return; // 그사이 설정을 바꿨다 — 그 응답이 최종 상태다
    }
    state = next;
    render();
  }

  void refresh();
  window.addEventListener("focus", () => {
    if (lastSuccess > 0 && Date.now() - lastSuccess >= REFRESH_MS) {
      void refresh();
    }
  });
  return { banner, footer };
}
