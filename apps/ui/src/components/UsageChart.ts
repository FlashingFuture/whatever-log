import type { RangeUsage } from "../api";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createProcessRow } from "./ProcessRow";
import { createUsageLegend } from "./UsageLegend";

injectStyle(
  "usage-chart",
  `
  .usage-chart {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .usage-chart-empty {
    color: ${theme.colors.textMuted};
  }
`,
);

/** 구간의 프로세스별 사용 시간 막대 차트. 어떤 구간인지(제목/라벨)는 호출부가 그린다. */
export function createUsageChart(usage: RangeUsage): HTMLElement {
  const container = document.createElement("div");

  if (usage.by_process.length === 0) {
    const empty = document.createElement("p");
    empty.className = "usage-chart-empty";
    empty.textContent = "기록된 사용 내역이 없습니다.";
    container.append(empty);
    return container;
  }

  // 가장 오래 떠 있던(total) 프로세스를 기준으로 막대 폭을 정한다 — 구간
  // 전체 길이(하루/한 주/한 달)를 기준으로 하면 거의 모든 막대가 짤막해져서
  // 비교가 어렵다.
  const maxTotal = Math.max(
    ...usage.by_process.map((row) => row.total_seconds),
  );

  const chart = document.createElement("div");
  chart.className = "usage-chart";
  for (const row of usage.by_process) {
    chart.append(createProcessRow(row, maxTotal));
  }

  container.append(createUsageLegend(), chart);
  return container;
}
