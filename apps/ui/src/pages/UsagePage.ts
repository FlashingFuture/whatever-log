import { fetchGoalProgress, fetchUsage } from "../api";
import { createGoalManager } from "../components/goals/GoalManager";
import { createPeriodView } from "../components/period/PeriodView";
import { createUsageChart } from "../components/usage/UsageChart";
import { createUsageSummary } from "../components/usage/UsageSummary";
import styles from "./UsagePage.module.css";

/**
 * 홈 화면: 왼쪽에 선택한 구간의 요약(목표 수행 시간·가장 길게 수행한 프로세스·목표 관리), 오른쪽에
 * 프로세스별 차트(집중 시간순). 구간 이동은 PeriodView가 맡고, 여기는 "구간 → 요약 + 차트"만
 * 정한다. 목표 관리 모달은 15초마다 다시 그려지는 내용 밖(페이지)에 두어, 열려 있는 동안 갱신에
 * 지워지지 않게 한다. 돌려주는 함수로 화면을 정리한다.
 */
export function mountUsagePage(root: HTMLElement): () => void {
  const goals = createGoalManager({ onChange: () => view.refresh() });

  const view = createPeriodView({
    loadContent: async (period) => {
      const [usage, progress] = await Promise.all([
        fetchUsage(period.start, period.end),
        // 목표를 못 불러와도 사용 현황은 보여 준다.
        fetchGoalProgress(period.start, period.end).catch(() => null),
      ]);
      const side = document.createElement("div");
      side.className = styles.side;
      side.append(
        createUsageSummary({ usage, progress, onManageGoals: goals.open }),
      );
      const dashboard = document.createElement("div");
      dashboard.className = styles.dashboard;
      dashboard.append(side, createUsageChart(usage));
      return dashboard;
    },
  });

  root.replaceChildren(view.element);
  return () => {
    view.destroy();
    goals.destroy();
  };
}
