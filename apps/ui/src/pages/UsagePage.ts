import { fetchGoalProgress, fetchGoalTotals, fetchUsage } from "../api";
import { createGoalManager } from "../components/goals/GoalManager";
import { createGoalSelector } from "../components/goals/GoalSelector";
import { createPeriodView } from "../components/period/PeriodView";
import { createUsageChart } from "../components/usage/UsageChart";
import { createUsageSummary } from "../components/usage/UsageSummary";
import { dayRange, settleSelection } from "../lib/goalSelection";
import { syncNotice } from "../lib/syncNotice";
import { navigate } from "../router/router";
import type { AccountStore } from "../state/accountStore";
import styles from "./UsagePage.module.css";

/**
 * 홈 화면: 맨 위에 목표 선택(목표 전체 / 목표 하나), 그 아래에 일/주/월 선택과 구간 이동, 그 아래에 왼쪽 요약(목표 수행 시간 `전체 | 현 기기`·
 * 달성률·가장 길게 수행한 프로세스·목표 관리)과 오른쪽 프로세스별 차트(집중 시간순). 구간 이동은 PeriodView가 맡고, 여기는 "구간 → 요약 + 차트"만
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
    // 목록에서 목표를 누르면 그 목표의 개요 화면으로 간다(연결 프로세스 관리는 그 화면의 단추로).
    onOpenGoal: (goal) => navigate({ name: "goal", goalId: goal.id }),
    // 15초마다 요약이 다시 그려져 열었던 버튼이 사라졌을 수 있다 — 지금 있는 버튼으로 포커스를 돌려준다.
    onClose: () =>
      root.querySelector<HTMLElement>("[data-goal-manage]")?.focus(),
  });

  // 고른 목표(null = 목표 전체). 목표가 지워지면 다음에 그릴 때 목표 전체로 돌아간다(settleSelection). 조회가 실패한 갱신은 선택을 바꾸지 않는다.
  let selectedGoalId: number | null = null;
  // 가장 최근에 시작한 조회의 번호. 구간을 빠르게 넘기면 조회가 겹치는데, PeriodView는 늦게 온 낡은 응답의 **화면**만 버린다 — 선택과 선택기의 목록은
  // 여기서 따로 지켜야 한다(안 그러면 낡은 조회의 목록이 현재 선택을 지우고, 선택기와 화면이 서로 다른 목록을 보여 준다).
  let latestLoad = 0;
  const selector = createGoalSelector({
    onSelect: (id) => {
      selectedGoalId = id;
      view.refresh();
    },
  });

  const view = createPeriodView({
    loadContent: async (period) => {
      const loadId = ++latestLoad;
      const { from, to } = dayRange(period.start, period.end);
      const [usage, progress, totals] = await Promise.all([
        fetchUsage(period.start, period.end),
        // 목표를 못 불러와도 사용 현황은 보여 준다.
        fetchGoalProgress(period.start, period.end).catch(() => null),
        // 다른 기기의 합계를 못 받아도(서버·네트워크) 이 PC의 값은 그대로 보여 준다 — "전체"만 "-"가 된다.
        fetchGoalTotals(from, to).catch(() => null),
      ]);
      // 목표 진행을 받았을 때만 선택을 정리한다. 조회가 실패했으면 이전 선택을 그대로 둔다(settleSelection).
      const settled = settleSelection(selectedGoalId, progress?.goals ?? null);
      // 선택과 선택기의 목록은 **가장 최근에 시작한 조회**만 바꾼다. 낡은 조회는 이 화면을 만들지만 어차피 PeriodView가 버린다.
      if (loadId === latestLoad) {
        selectedGoalId = settled;
        if (progress !== null) {
          selector.update({ goals: progress.goals, selectedId: settled });
        }
      }
      const side = document.createElement("div");
      side.className = styles.side;
      side.append(
        createUsageSummary({
          usage,
          progress,
          totals,
          selectedGoalId: settled,
          onManageGoals: goals.open,
        }),
      );
      const dashboard = document.createElement("div");
      dashboard.className = styles.dashboard;
      dashboard.append(side, createUsageChart(usage));
      return dashboard;
    },
  });

  // 맨 위에 목표 선택, 그 아래에 일/주/월 선택과 내용. 선택기는 15초마다 다시 그려지는 내용 바깥에 붙어 있어서 열린 목록·포커스가 갱신에 영향받지 않는다.
  const goalBar = document.createElement("div");
  goalBar.className = styles.goalBar;
  goalBar.append(selector.element);
  root.replaceChildren(goalBar, view.element);
  return () => {
    view.destroy();
    selector.destroy();
    goals.destroy();
  };
}
