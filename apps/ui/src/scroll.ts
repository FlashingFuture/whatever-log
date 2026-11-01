/**
 * 뒤로 가기로 돌아온 화면의 스크롤 위치를 되살린다.
 *
 * 화면 내용은 비동기로 그려져서, 돌아온 직후엔 문서가 짧아 원하는 위치까지 스크롤할
 * 수 없다. 위치에 닿을 때까지(또는 시간이 다 될 때까지) 매 프레임 다시 시도한다.
 * 사용자가 직접 스크롤하려는 순간에는 멈춘다. 돌려주는 함수로 중단할 수 있다.
 */
const MAX_FRAMES = 120; // 60fps 기준 약 2초

export function restoreScroll(y: number): () => void {
  if (y <= 0) {
    window.scrollTo(0, 0);
    return () => {};
  }

  let frames = 0;
  let frame = 0;
  const stop = (): void => {
    cancelAnimationFrame(frame);
    for (const type of USER_SCROLL_EVENTS) {
      window.removeEventListener(type, stop);
    }
  };
  for (const type of USER_SCROLL_EVENTS) {
    window.addEventListener(type, stop, { passive: true });
  }

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

const USER_SCROLL_EVENTS = ["wheel", "touchstart", "keydown"] as const;
