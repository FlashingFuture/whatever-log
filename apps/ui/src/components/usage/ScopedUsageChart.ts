import type { GoalProgressResponse, RangeUsage } from "../../api";
import { goalTargetsFromProgress } from "../../lib/goalOverview";
import { maxOf } from "../../lib/stats";
import { createEmptyNotice } from "../common/EmptyNotice";
import { createGoalTargetColumn } from "./GoalTargetColumn";
import { createColumnChart, createUsageChart } from "./UsageChart";

export interface ScopedUsageChartProps {
  usage: RangeUsage;
  /** 구간의 목표 진행. 불러오지 못했으면 null. */
  progress: GoalProgressResponse | null;
  /** 고른 목표(null = 목표 전체). */
  selectedGoalId: number | null;
  /** 고른 목표에 연결한 프로세스가 없을 때 "프로세스 추가"를 눌렀다 — 그 목표의 연결 관리 화면으로 간다. */
  onAddProcesses: (goalId: number) => void;
}

/**
 * 홈 오른쪽 차트. **목표 전체**를 보는 중이면 구간의 모든 프로세스를(지금까지와 같다), **목표 하나**를 고르면 그 목표에 연결한 프로세스·사이트만 보인다.
 * 연결한 것이 하나도 없으면 빈 차트 대신 "등록된 프로세스가 없어요"와 연결하러 가는 버튼을 보인다.
 * 목표 진행을 불러오지 못한 채 목표를 골랐다면(일시적 실패) 무엇을 연결했는지 알 수 없어서 다른 프로세스를 대신 보이지 않고 안내만 한다.
 */
export function createScopedUsageChart(
  props: ScopedUsageChartProps,
): HTMLElement {
  if (props.selectedGoalId === null) {
    return createUsageChart(props.usage);
  }
  const goal = props.progress?.goals.find(
    (candidate) => candidate.id === props.selectedGoalId,
  );
  if (goal === undefined) {
    const note = document.createElement("p");
    note.textContent =
      "목표 정보를 불러오지 못했어요. 잠시 뒤 다시 보여 드릴게요.";
    return note;
  }
  const targets = goalTargetsFromProgress(goal, props.usage.by_process);
  if (targets.length === 0) {
    return createEmptyNotice({
      text: "등록된 프로세스가 없습니다. 새로 등록해 보세요.",
      actionLabel: "프로세스 추가",
      onAction: () => props.onAddProcesses(goal.id),
    });
  }
  const maxTotal = maxOf(targets, (target) => target.usage.total_seconds);
  return createColumnChart(
    targets.map((target) => createGoalTargetColumn(target, maxTotal)),
    "",
  );
}
