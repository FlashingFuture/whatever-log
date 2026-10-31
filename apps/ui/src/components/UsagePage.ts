import { fetchUsage } from "../api";
import { createPeriodView } from "./PeriodView";
import { createUsageChart } from "./UsageChart";

/**
 * 홈 화면: 선택한 구간의 프로세스별 사용 시간. 구간 이동은 PeriodView가 맡고, 여기는
 * "구간 → 프로세스별 차트"만 정한다. 돌려주는 함수로 화면을 정리한다.
 */
export function mountUsagePage(root: HTMLElement): () => void {
  const title = document.createElement("h1");
  title.textContent = "사용 현황";

  const view = createPeriodView({
    loadContent: async (period) =>
      createUsageChart(await fetchUsage(period.start, period.end)),
  });

  root.replaceChildren(title, view.element);
  return view.destroy;
}
