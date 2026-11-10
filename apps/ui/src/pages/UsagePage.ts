import { fetchGoalProgress, fetchGoalTotals, fetchUsage } from "../api";
import { createGoalManager } from "../components/goals/GoalManager";
import { createGoalSelector } from "../components/goals/GoalSelector";
import { createPeriodView } from "../components/period/PeriodView";
import { createUsageChart } from "../components/usage/UsageChart";
import { createUsageSummary } from "../components/usage/UsageSummary";
import { dayRange, resolveSelection } from "../lib/goalSelection";
import { syncNotice } from "../lib/syncNotice";
import type { AccountStore } from "../state/accountStore";
import styles from "./UsagePage.module.css";

/**
 * 홈 화면: 왼쪽에 선택한 구간의 요약(목표 선택·목표 수행 시간 `전체 | 현 기기`·가장 길게 수행한 프로세스·목표 관리), 오른쪽에
 * 프로세스별 차트(집중 시간순). 구간 이동은 PeriodView가 맡고, 여기는 "구간 → 요약 + 차트"만
 * 정한다. 목표 관리 모달과 목표 선택기는 15초마다 다시 그려지는 내용 밖(페이지)에 두어, 열려 있는 동안 갱신에
 * 지워지지 않게 한다. 고른 목표는 이 페이지가 들고 있다(화면을 떠나면 목표 전체로 돌아간다). 돌려주는 함수로 화면을 정리한다.
 */
export function mountUsagePage(
  root: HTMLElement,
  options: { account: AccountStore },
): () => void {
  const goals = createGoalManager({
    // 로그인한 상태에서 만드는 목표는 이름·목표 시간·요일이 서버에도 저장되므로, 목표를 만드는 화면에서 알린다.
    notice: () => syncNotice(options.account.getState()),
    onChange: () => view.refresh(),
    // 15초마다 요약이 다시 그려져 열었던 버튼이 사라졌을 수 있다 — 지금 있는 버튼으로 포커스를 돌려준다.
    onClose: () =>
      root.querySelector<HTMLElement>("[data-goal-manage]")?.focus(),
  });

  // 고른 목표(null = 목표 전체). 목표가 지워지면 다음에 그릴 때 목표 전체로 돌아간다(resolveSelection).
  let selectedGoalId: number | null = null;
  const selector = createGoalSelector({
    onSelect: (id) => {
      selectedGoalId = id;
      view.refresh();
    },
  });

  const view = createPeriodView({
    loadContent: async (period) => {
      const { from, to } = dayRange(period.start, period.end);
      const [usage, progress, totals] = await Promise.all([
        fetchUsage(period.start, period.end),
        // 목표를 못 불러와도 사용 현황은 보여 준다.
        fetchGoalProgress(period.start, period.end).catch(() => null),
        // 다른 기기의 합계를 못 받아도(서버·네트워크) 이 PC의 값은 그대로 보여 준다 — "전체"만 "-"가 된다.
        fetchGoalTotals(from, to).catch(() => null),
      ]);
      selectedGoalId = resolveSelection(selectedGoalId, progress?.goals ?? []);
      selector.update({
        goals: progress?.goals ?? [],
        selectedId: selectedGoalId,
      });
      // 선택기를 새 내용에 옮겨 끼우면 포커스를 잃는다 — 키보드로 단추에 있던 사용자가 갱신마다 쫓겨나지 않게, 새 내용이 붙은 뒤 되돌린다.
      const selectorHadFocus = selector.hasFocus();
      const side = document.createElement("div");
      side.className = styles.side;
      side.append(
        createUsageSummary({
          usage,
          progress,
          totals,
          selectedGoalId,
          selector: selector.element,
          onManageGoals: goals.open,
        }),
      );
      const dashboard = document.createElement("div");
      dashboard.className = styles.dashboard;
      dashboard.append(side, createUsageChart(usage));
      if (selectorHadFocus) {
        setTimeout(selector.focus, 0); // PeriodView가 내용을 붙인 다음(같은 틱의 뒤)
      }
      return dashboard;
    },
  });

  root.replaceChildren(view.element);
  return () => {
    view.destroy();
    selector.destroy();
    goals.destroy();
  };
}
