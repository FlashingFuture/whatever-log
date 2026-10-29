import { fetchUsage } from "./api";
import { renderErrorView } from "./components/ErrorView";
import { renderUsageChart } from "./components/UsageChart";
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

// recorder의 기본 샘플링 간격(15초, apps/recorder/__main__.py의
// DEFAULT_INTERVAL_SECONDS)과 맞춰서, 화면이 "실시간으로 쌓이는" 느낌이
// 나게 주기적으로 다시 불러온다.
const REFRESH_INTERVAL_MS = 15_000;

function loadUsage(app: Element, { isBackgroundRefresh = false } = {}): void {
  fetchUsage()
    .then((usage) => renderUsageChart(app, usage))
    .catch((error: unknown) => {
      // 주기적 갱신이 일시적으로 실패한 거라면(hub가 잠깐 재시작하는 중 등),
      // 이미 잘 보여주고 있던 화면을 에러 화면으로 덮어쓰지 않는다 — 다음
      // 주기에 다시 시도된다. 최초 로드 실패나 "다시 시도" 클릭 때만 에러를
      // 보여준다.
      if (!isBackgroundRefresh) {
        renderErrorView(app, String(error), () => loadUsage(app));
      }
    });
}

const app = document.querySelector("#app");
if (app) {
  loadUsage(app);
  setInterval(
    () => loadUsage(app, { isBackgroundRefresh: true }),
    REFRESH_INTERVAL_MS,
  );
}
