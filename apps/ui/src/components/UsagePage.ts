import { fetchUsage } from "../api";
import { createPeriodView } from "./PeriodView";
import { createUsageChart } from "./UsageChart";
import styles from "./UsagePage.module.css";
import { createUsageSummary } from "./UsageSummary";

/**
 * 홈 화면: 왼쪽에 선택한 구간의 요약(총 사용 시간·가장 많이 쓴 프로그램), 오른쪽에
 * 프로세스별 차트(집중 시간순). 구간 이동은 PeriodView가 맡고, 여기는 "구간 → 요약 + 차트"만
 * 정한다. 돌려주는 함수로 화면을 정리한다.
 */
export function mountUsagePage(root: HTMLElement): () => void {
  const title = document.createElement("h1");
  title.textContent = "사용 현황";

  const view = createPeriodView({
    loadContent: async (period) => {
      const usage = await fetchUsage(period.start, period.end);
      const side = document.createElement("div");
      side.className = styles.side;
      side.append(createUsageSummary(usage));
      const dashboard = document.createElement("div");
      dashboard.className = styles.dashboard;
      dashboard.append(side, createUsageChart(usage));
      return dashboard;
    },
  });

  root.replaceChildren(title, view.element);
  return view.destroy;
}
