/**
 * 화면 전환(홈 ↔ 프로세스 상세)을 위한 가벼운 해시 라우터.
 *
 * 주소를 `#/process/<이름>` 꼴로 두면 서버 설정 없이(pywebview가 어떤 주소로 띄워도)
 * 새로고침과 뒤로 가기가 된다. 라이브러리 없이 history API만 쓴다.
 *
 * 앱 안에서 몇 번 이동했는지를 history.state.depth에 적어 둔다 — "돌아가기"가
 * 앱 밖(처음 열린 페이지 이전)으로 나가 버리지 않게, depth가 0이면 홈으로 보낸다.
 * 파싱·주소 만들기는 순수 함수라 DOM 없이 테스트한다.
 */

export type Route = { name: "home" } | { name: "process"; process: string };

export const HOME: Route = { name: "home" };

const PROCESS_PREFIX = "#/process/";

export function parseRoute(hash: string): Route {
  if (hash.startsWith(PROCESS_PREFIX)) {
    const raw = hash.slice(PROCESS_PREFIX.length);
    if (raw) {
      try {
        return { name: "process", process: decodeURIComponent(raw) };
      } catch {
        // 깨진 퍼센트 인코딩이면 홈으로 보낸다.
      }
    }
  }
  return HOME;
}

export function routeHref(route: Route): string {
  return route.name === "process"
    ? `${PROCESS_PREFIX}${encodeURIComponent(route.process)}`
    : "#/";
}

export function isSameRoute(a: Route, b: Route): boolean {
  return routeHref(a) === routeHref(b);
}

export function currentRoute(): Route {
  return parseRoute(window.location.hash);
}

function currentDepth(): number {
  const state = window.history.state as { depth?: number } | null;
  return state?.depth ?? 0;
}

type Listener = () => void;
const listeners = new Set<Listener>();
let listening = false;

function notify(): void {
  for (const listener of [...listeners]) {
    listener();
  }
}

/** 경로가 바뀔 때마다 부른다(이동·뒤로 가기 모두). 돌려받은 함수로 해제한다. */
export function onRouteChange(listener: Listener): () => void {
  if (!listening) {
    listening = true;
    // 해시만 바뀌는 이동도, history.back()도 popstate로 온다.
    window.addEventListener("popstate", notify);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function navigate(route: Route): void {
  if (isSameRoute(route, currentRoute())) {
    return;
  }
  window.history.pushState({ depth: currentDepth() + 1 }, "", routeHref(route));
  notify();
}

/**
 * 앱 안에서 온 길이 있으면 한 단계 뒤로, 없으면(상세 주소를 바로 열었거나 새로
 * 고침한 경우) 홈으로 간다 — 앱 밖으로 나가 버리지 않게.
 */
export function goBack(): void {
  if (currentDepth() > 0) {
    window.history.back();
  } else {
    navigate(HOME);
  }
}

/**
 * route로 가는 링크. 주소(href)를 갖고 있어서 키보드 포커스·스크린 리더에서 링크로
 * 읽히고, 보통의 왼쪽 클릭만 가로채 앱 안에서 이동시킨다.
 */
export function createRouteLink(route: Route): HTMLAnchorElement {
  const link = document.createElement("a");
  link.href = routeHref(route);
  link.addEventListener("click", (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    navigate(route);
  });
  return link;
}
