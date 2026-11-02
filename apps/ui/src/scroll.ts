/**
 * 뒤로/앞으로 가기로 돌아온 화면의 스크롤 위치를 되살린다.
 *
 * 화면 내용은 비동기로 그려져서(hub 응답이 느리면 몇 초 뒤에도), 돌아온 직후엔 문서가
 * 짧아 원하는 위치까지 스크롤할 수 없다. 그래서 프레임 수로 포기하지 않고 문서 크기가
 * 바뀔 때마다(ResizeObserver) 다시 시도해, 내용이 언제 그려지든 위치에 닿으면 끝낸다.
 * 사용자가 직접 스크롤하려는 순간(휠·터치·스크롤 막대·스크롤 키)이나 화면을 떠날 때
 * (돌려주는 함수)에는 멈춘다.
 *
 * 위치는 현재 기록(history entry)에 스크롤할 때마다 적어 둔다(trackScroll). 이동 시점에만
 * 적으면 뒤로 간 뒤 앞으로 돌아올 때 떠난 기록에 위치가 없다.
 */
// 내용이 영영 안 그려지는 경우(에러 화면 등)에 관찰을 무한정 붙들고 있지 않는 안전장치.
// hub 요청 제한 시간(최대 60초)보다 길게 둔다.
export const MAX_RESTORE_MS = 90_000;

// 페이지를 스크롤하는 키. Tab·글자 키 등으로는 복원을 멈추지 않는다(로딩 중에 Tab을
// 눌렀다고 위치를 잃으면 안 된다).
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
]);

export function isScrollKey(key: string): boolean {
  return SCROLL_KEYS.has(key);
}

// 복원이 진행 중인 동안에는 위치를 기록에 적지 않는다 — 내용이 다 그려지기 전의 짧은
// 문서에서 밀린 값(또는 복원 중간값)으로 저장돼 있던 위치를 덮어쓰면 안 된다.
let restoring = 0;

export function restoreScroll(y: number): () => void {
  if (y <= 0) {
    window.scrollTo(0, 0);
    return () => {};
  }

  restoring += 1;
  let stopped = false;
  let observer: ResizeObserver | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const stop = (): void => {
    if (stopped) {
      return;
    }
    stopped = true;
    restoring -= 1;
    observer?.disconnect();
    clearTimeout(timer);
    window.removeEventListener("wheel", stop);
    window.removeEventListener("touchstart", stop);
    window.removeEventListener("pointerdown", stop);
    window.removeEventListener("keydown", onKeyDown);
  };
  const onKeyDown = (event: KeyboardEvent): void => {
    if (isScrollKey(event.key)) {
      stop();
    }
  };
  const attempt = (): void => {
    if (stopped) {
      return;
    }
    window.scrollTo(0, y);
    if (Math.abs(window.scrollY - y) <= 1) {
      stop();
    }
  };

  window.addEventListener("wheel", stop, { passive: true });
  window.addEventListener("touchstart", stop, { passive: true });
  window.addEventListener("pointerdown", stop, { passive: true });
  window.addEventListener("keydown", onKeyDown);
  observer = new ResizeObserver(attempt);
  observer.observe(document.documentElement);
  timer = setTimeout(stop, MAX_RESTORE_MS);

  attempt();
  return stop;
}

/** 스크롤할 때마다(프레임당 한 번) save(현재 위치)를 부른다. 복원 중에는 부르지 않는다. */
export function trackScroll(save: (y: number) => void): void {
  let scheduled = false;
  window.addEventListener(
    "scroll",
    () => {
      if (scheduled) {
        return;
      }
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        if (restoring === 0) {
          save(window.scrollY);
        }
      });
    },
    { passive: true },
  );
}
