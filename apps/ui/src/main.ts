import { mountAppLayout } from "./components/AppLayout";
import { mountProcessPage } from "./components/ProcessPage";
import { mountUsagePage } from "./components/UsagePage";
import {
  canGoBack,
  currentRoute,
  goBack,
  HOME,
  navigate,
  onRouteChange,
} from "./router";
import { injectStyle } from "./styles/injectStyle";
import { theme } from "./theme";

injectStyle(
  "global",
  `
  body {
    font: 16px/1.5 system-ui, "Segoe UI", Roboto, sans-serif;
    margin: 2rem;
    background: ${theme.colors.background};
    color: ${theme.colors.text};
  }
`,
);

const app = document.querySelector("#app");
if (app) {
  const layout = mountAppLayout(app, {
    onHome: () => navigate(HOME),
    onBack: goBack,
  });

  // 지금 화면의 정리 함수. 화면을 갈아 끼우기 전에 부른다(타이머·키보드 리스너 해제).
  let destroyPage: (() => void) | null = null;

  function renderRoute(): void {
    destroyPage?.();
    const route = currentRoute();
    destroyPage =
      route.name === "process"
        ? mountProcessPage(layout.content, route.process)
        : mountUsagePage(layout.content);
    layout.nav.update({
      canGoHome: route.name !== "home",
      canGoBack: canGoBack(),
    });
    window.scrollTo(0, 0);
  }

  onRouteChange(renderRoute);
  renderRoute();
}
