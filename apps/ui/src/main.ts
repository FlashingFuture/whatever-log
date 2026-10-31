import { mountLayout } from "./components/Layouts";
import { mountProcessPage } from "./components/ProcessPage";
import { mountUsagePage } from "./components/UsagePage";
import {
  currentRoute,
  goBack,
  type NavigationKind,
  onRouteChange,
  type Route,
  savedScroll,
} from "./router";
import { type LayoutName, layoutOf } from "./routes";
import { restoreScroll } from "./scroll";
import "./styles/global.css";

/** 라우트에 맞는 화면을 content에 그리고, 그 화면을 정리하는 함수를 돌려준다. */
function mountPage(content: HTMLElement, route: Route): () => void {
  return route.name === "process"
    ? mountProcessPage(content, route.process)
    : mountUsagePage(content);
}

const app = document.querySelector("#app");
if (app) {
  const root = app;
  let layout: LayoutName | null = null;
  let content: HTMLElement | null = null;
  // 지금 화면의 정리 함수. 화면을 갈아 끼우기 전에 부른다(타이머·키보드 리스너 해제).
  let destroyPage: (() => void) | null = null;
  let cancelScrollRestore: () => void = () => {};
  // 스크롤 위치는 기록(history entry)마다 우리가 저장·복원한다.
  window.history.scrollRestoration = "manual";

  function renderRoute(kind: NavigationKind | "initial"): void {
    cancelScrollRestore();
    destroyPage?.();
    destroyPage = null;

    const route = currentRoute();
    const nextLayout = layoutOf(route);
    // 레이아웃은 바뀔 때만 다시 그린다(같은 틀 안에서의 이동은 틀을 그대로 둔다).
    if (nextLayout !== layout || content === null) {
      content = mountLayout(root, nextLayout, { onBack: goBack });
      layout = nextLayout;
    }
    destroyPage = mountPage(content, route);
    // 뒤로 가기로 돌아온 화면은 떠날 때의 위치로, 새로 들어간 화면은 맨 위로.
    cancelScrollRestore = restoreScroll(kind === "pop" ? savedScroll() : 0);
  }

  onRouteChange(renderRoute);
  renderRoute("initial");
}
