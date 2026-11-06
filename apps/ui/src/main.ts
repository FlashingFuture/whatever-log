import { cancelLogin, fetchAccount, logout, startLogin } from "./api";
import { mountLayout } from "./layouts/Layouts";
import { createNavBar } from "./layouts/NavBar";
import { mountProcessPage } from "./pages/ProcessPage";
import { mountUsagePage } from "./pages/UsagePage";
import {
  currentRoute,
  goBack,
  type NavigationKind,
  onRouteChange,
  type Route,
  savedScroll,
  saveScroll,
} from "./router/router";
import { type LayoutName, layoutOf } from "./router/routes";
import { restoreScroll, trackScroll } from "./router/scroll";
import { createAccountStore } from "./state/accountStore";
import "./styles/global.css";

/** 라우트에 맞는 화면을 content에 그리고, 그 화면을 정리하는 함수를 돌려준다. */
function mountPage(content: HTMLElement, route: Route): () => void {
  return route.name === "process"
    ? mountProcessPage(content, route.process)
    : mountUsagePage(content);
}

const app = document.querySelector("#app");
if (app) {
  // 로그인 상태는 앱 전체가 하나를 같이 쓴다(상단 막대가 보여 주고, 앞으로 서버 기능이 확인한다).
  // 진실은 hub에 있고 이 저장소는 사본이다 — 시작할 때와 창으로 돌아올 때 hub에 다시 묻는다(docs/ui-state.md).
  const account = createAccountStore({
    api: { fetchAccount, startLogin, cancelLogin, logout },
  });
  const navBar = createNavBar(account);
  // 상단 막대는 한 번만 그리고, 화면 틀(레이아웃)은 그 아래 자리(stage)에 갈아 끼운다.
  const stage = document.createElement("div");
  app.replaceChildren(navBar.element, stage);
  void account.refresh();
  window.addEventListener("focus", () => void account.refresh());

  const root = stage;
  let layout: LayoutName | null = null;
  let content: HTMLElement | null = null;
  // 지금 화면의 정리 함수. 화면을 갈아 끼우기 전에 부른다(타이머·키보드 리스너 해제).
  let destroyPage: (() => void) | null = null;
  let cancelScrollRestore: () => void = () => {};
  // 스크롤 위치는 기록(history entry)마다 우리가 저장·복원한다.
  window.history.scrollRestoration = "manual";
  trackScroll(saveScroll);

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
