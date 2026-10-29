import type { RangeUsage } from "../api";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createBarRow } from "./BarRow";

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
  .usage-chart-legend {
    display: flex;
    gap: 1rem;
    font-size: 0.8rem;
    color: ${theme.colors.textMuted};
    margin-bottom: 0.4rem;
  }
  .usage-chart-legend-dot {
    display: inline-block;
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    margin-right: 0.3rem;
  }
`,
);

function legendItem(color: string, label: string): HTMLSpanElement {
  const item = document.createElement("span");

  const dot = document.createElement("span");
  dot.className = "usage-chart-legend-dot";
  dot.style.background = color;

  item.append(dot, document.createTextNode(label));
  return item;
}

export function renderUsageChart(app: Element, usage: RangeUsage): void {
  app.innerHTML = "<h1>최근 24시간 사용 현황</h1>";

  if (usage.by_process.length === 0) {
    const empty = document.createElement("p");
    empty.className = "usage-chart-empty";
    empty.textContent = "기록된 사용 내역이 없습니다.";
    app.append(empty);
    return;
  }

  const legend = document.createElement("div");
  legend.className = "usage-chart-legend";
  legend.append(
    legendItem(theme.colors.active, "활성"),
    legendItem(theme.colors.idle, "유휴"),
    legendItem(theme.colors.backgroundSegment, "백그라운드"),
  );

  // 가장 오래 떠 있던(total) 프로세스를 기준으로 막대 폭을 정한다 — 범위
  // 전체 길이(24시간)를 기준으로 하면 거의 모든 막대가 짤막해져서 비교가
  // 어렵다.
  const maxTotal = Math.max(
    ...usage.by_process.map((row) => row.total_seconds),
  );

  const chart = document.createElement("div");
  chart.className = "usage-chart";
  for (const row of usage.by_process) {
    chart.append(createBarRow(row, maxTotal));
  }

  app.append(legend, chart);
}
