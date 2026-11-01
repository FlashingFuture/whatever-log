/**
 * 뒤로/앞으로 가기로 돌아온 화면의 스크롤 위치를 되살린다.
 *
 * 화면 내용은 비동기로 그려져서, 돌아온 직후엔 문서가 짧아 원하는 위치까지 스크롤할
 * 수 없다. 위치에 닿을 때까지(또는 시간이 다 될 때까지) 매 프레임 다시 시도한다.
 * 사용자가 직접 스크롤하려는 순간(휠·터치·스크롤 키)에는 멈춘다. 돌려주는 함수로
 * 중단할 수 있다.
 *
 * 위치는 현재 기록(history entry)에 스크롤할 때마다 적어 둔다(trackScroll). 이동 시점에만
 * 적으면 뒤로 간 뒤 앞으로 돌아올 때 떠난 기록에 위치가 없다.
 */
const MAX_FRAMES = 120; // 60fps 기준 약 2초

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
  let frame = 0;
  let stopped = false;
  const stop = (): void => {
    if (stopped) {
      return;
    }
    stopped = true;
    restoring -= 1;
    cancelAnimationFrame(frame);
    window.removeEventListener("wheel", stop);
    window.removeEventListener("touchstart", stop);
    window.removeEventListener("keydown", onKeyDown);
  };
  const onKeyDown = (event: KeyboardEvent): void => {
    if (isScrollKey(event.key)) {
      stop();
    }
  };
  window.addEventListener("wheel", stop, { passive: true });
  window.addEventListener("touchstart", stop, { passive: true });
  window.addEventListener("keydown", onKeyDown);

  let frames = 0;
  const attempt = (): void => {
    window.scrollTo(0, y);
    frames += 1;
    if (Math.abs(window.scrollY - y) <= 1 || frames >= MAX_FRAMES) {
      stop();
      return;
    }
    frame = requestAnimationFrame(attempt);
  };
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
