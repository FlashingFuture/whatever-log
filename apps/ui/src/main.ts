import { cancelLogin, fetchAccount, logout, startLogin } from "./api";
import { createSyncDialog } from "./components/sync/SyncDialog";
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
import { type AccountStore, createAccountStore } from "./state/accountStore";
import "./styles/global.css";

/** 라우트에 맞는 화면을 content에 그리고, 그 화면을 정리하는 함수를 돌려준다. */
function mountPage(
  content: HTMLElement,
  route: Route,
  account: AccountStore,
): () => void {
  return route.name === "process"
    ? mountProcessPage(content, route.process)
    : mountUsagePage(content, { account });
}

const app = document.querySelector("#app");
if (app) {
  // 로그인 상태는 앱 전체가 하나를 같이 쓴다(상단 막대가 보여 주고, 앞으로 서버 기능이 확인한다).
  // 진실은 hub에 있고 이 저장소는 사본이다 — 시작할 때와 창으로 돌아올 때 hub에 다시 묻는다(docs/ui-state.md).
  const account = createAccountStore({
    api: { fetchAccount, startLogin, cancelLogin, logout },
  });
  // 로그인한 뒤 "어떤 목표를 서버에 넘길까요?"를 묻는 창. 목표가 바뀌면(합치기·가져오기) 현재 화면을 다시 그린다.
  const syncDialog = createSyncDialog({
    onGoalsChanged: () => renderRoute("initial"),
    onSignedOut: () => void account.refresh(),
  });
  // 로그인이 막 끝난 순간(로그인 중 → 로그인됨)에만 자동으로 연다. 앱을 다시 열 때마다 묻지 않는다.
  let previousPhase = account.getState().phase;
  account.subscribe((state) => {
    if (previousPhase === "signingIn" && state.phase === "signedIn") {
      void syncDialog.open({ afterLogin: true });
    }
    previousPhase = state.phase;
  });
  const navBar = createNavBar(account, {
    onOpenSync: () => void syncDialog.open({ afterLogin: false }),
  });
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
    destroyPage = mountPage(content, route, account);
    // 뒤로 가기로 돌아온 화면은 떠날 때의 위치로, 새로 들어간 화면은 맨 위로.
    cancelScrollRestore = restoreScroll(kind === "pop" ? savedScroll() : 0);
  }

  onRouteChange(renderRoute);
  renderRoute("initial");
}
