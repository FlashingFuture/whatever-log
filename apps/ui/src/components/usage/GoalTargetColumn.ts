import type { GoalTarget } from "../../lib/goalOverview";
import { createUsageColumn } from "./ProcessColumn";
import { createProcessIcon, createSiteIcon } from "./ProcessIcon";

/**
 * 목표에 연결한 대상(프로세스 또는 사이트) 하나의 차트 칸. 사이트는 사이트 아이콘에 그 사이트를 연 브라우저 아이콘을 작게 겹쳐 붙이고, 누르면 그 브라우저의 상세로 간다.
 * 목표 개요 화면과 홈의 목표 보기가 같이 쓴다.
 */
export function createGoalTargetColumn(
  target: GoalTarget,
  maxTotal: number,
): HTMLElement {
  if (target.kind === "process") {
    return createUsageColumn(
      {
        name: target.process,
        fullName: target.process,
        usage: target.usage,
        icon: createProcessIcon(target.process),
        route: { name: "process", process: target.process },
      },
      maxTotal,
    );
  }
  return createUsageColumn(
    {
      name: target.domain,
      fullName: `${target.domain} (${target.browser})`,
      usage: target.usage,
      icon: createSiteIcon(target.domain),
      badge: createProcessIcon(target.browser),
      route: { name: "process", process: target.browser },
    },
    maxTotal,
  );
}
