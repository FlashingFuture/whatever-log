import { fetchSyncStatus, type SyncStatus } from "../../api";
import { chipFor, pollIntervalMs, type Tone } from "../../lib/syncStatus";
import styles from "./SyncStatusChip.module.css";

export interface SyncStatusChip {
  element: HTMLElement;
  /** 지금 상태를 다시 묻는다(동기화를 막 켰거나 적용했을 때). */
  refresh: () => Promise<void>;
  /** 로그인한 동안만 상태를 주기적으로 묻는다. false면 멈추고 칩을 숨긴다. */
  setActive: (active: boolean) => void;
  destroy: () => void;
}

export interface SyncStatusChipOptions {
  /** 테스트·미리보기가 바꿀 수 있다. */
  fetchStatus?: () => Promise<SyncStatus>;
  now?: () => Date;
  setTimer?: (callback: () => void, ms: number) => () => void;
}

const TONE_CLASS: Record<Tone, string> = {
  neutral: styles.neutral,
  good: styles.good,
  warn: styles.warn,
  bad: styles.bad,
};

/**
 * 상단 막대의 동기화 상태 칩("동기화됨 · 5분 전", "에이전트 멈춤", "동기화 오류" …). 상태를 주기적으로 묻고(정상 30초, 문제 15초),
 * 동기화를 켜지 않았거나 상태를 읽지 못하면 아무것도 그리지 않는다 — 동기화를 안 쓰는 사람에게 상태를 들이밀지 않고, hub가 꺼져도
 * 이 칩이 오류를 띄우지 않는다(그 상황은 계정 영역이 이미 알린다).
 *
 * 색에만 기대지 않도록 글자와 함께 보여 주고(톤 앞의 점은 장식), 자세한 안내(무엇을 하면 되는지)는 마우스를 올리면 나온다.
 * 상태는 이 칩 안의 일시적 값이라 저장소가 필요 없다(docs/ui-state.md).
 */
export function createSyncStatusChip(
  options: SyncStatusChipOptions = {},
): SyncStatusChip {
  const fetchStatus = options.fetchStatus ?? fetchSyncStatus;
  const now = options.now ?? (() => new Date());
  const setTimer =
    options.setTimer ??
    ((callback, ms) => {
      const id = setTimeout(callback, ms);
      return () => clearTimeout(id);
    });

  const element = document.createElement("span");
  element.className = styles.chip;
  element.setAttribute("role", "status");
  element.hidden = true;

  let active = false;
  let ticket = 0;
  let cancelTimer: (() => void) | null = null;
  let current: SyncStatus | null = null;

  function render(): void {
    const chip = active && current ? chipFor(current, now()) : null;
    if (chip === null) {
      element.hidden = true;
      element.textContent = "";
      element.removeAttribute("title");
      return;
    }
    element.hidden = false;
    element.className = `${styles.chip} ${TONE_CLASS[chip.tone]}`;
    element.textContent = chip.label;
    element.title = chip.detail;
  }

  function schedule(): void {
    cancelTimer?.();
    cancelTimer = null;
    if (!active) {
      return;
    }
    cancelTimer = setTimer(() => {
      cancelTimer = null;
      void refresh();
    }, pollIntervalMs(current));
  }

  async function refresh(): Promise<void> {
    if (!active) {
      return;
    }
    const mine = ++ticket;
    try {
      const loaded = await fetchStatus();
      if (mine === ticket && active) {
        current = loaded;
      }
    } catch {
      // 상태를 읽지 못해도(hub가 꺼짐 등) 칩이 오류를 띄우지는 않는다. 직전 값을 그대로 두고 다시 묻는다.
    }
    if (mine === ticket) {
      render();
      schedule();
    }
  }

  return {
    element,
    refresh,
    setActive(next) {
      if (next === active) {
        return;
      }
      active = next;
      ticket += 1; // 진행 중이던 요청의 응답은 버린다
      if (active) {
        void refresh();
      } else {
        cancelTimer?.();
        cancelTimer = null;
        current = null;
        render();
      }
    },
    destroy() {
      active = false;
      ticket += 1;
      cancelTimer?.();
      element.remove();
    },
  };
}
