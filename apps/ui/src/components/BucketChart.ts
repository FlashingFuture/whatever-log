import type { ProcessSeries } from "../api";
import { formatBucketLabel, type PeriodUnit } from "../period";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createUsageLegend } from "./UsageLegend";
import { createUsageRow, formatDuration } from "./UsageRow";

injectStyle(
  "bucket-chart",
  `
  .bucket-chart {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .bucket-chart-empty {
    color: ${theme.colors.textMuted};
  }
  .bucket-chart-summary {
    margin: 0 0 0.75rem;
    color: ${theme.colors.textMuted};
    font-size: 0.9rem;
  }
  .bucket-chart-label {
    color: ${theme.colors.text};
    font-variant-numeric: tabular-nums;
  }
`,
);

function sum(series: ProcessSeries, field: "active_seconds" | "total_seconds") {
  return series.buckets.reduce((total, bucket) => total + bucket[field], 0);
}

/**
 * 한 프로세스의 칸별(일: 시간, 주/월: 날짜) 사용 시간. 홈의 프로세스 목록과 같은
 * 줄 모양을 쓰되, 줄이 프로세스가 아니라 시간 칸이다. 칸마다 한 줄씩 위에서
 * 아래로 늘어놓고, 기록이 없는 칸도 빈 막대로 남겨 시간의 흐름이 이어져 보이게 한다.
 */
export function createBucketChart(
  unit: PeriodUnit,
  series: ProcessSeries,
): HTMLElement {
  const container = document.createElement("div");

  const total = sum(series, "total_seconds");
  if (total === 0) {
    const empty = document.createElement("p");
    empty.className = "bucket-chart-empty";
    empty.textContent = "이 구간에는 기록된 사용 내역이 없습니다.";
    container.append(empty);
    return container;
  }

  const summary = document.createElement("p");
  summary.className = "bucket-chart-summary";
  summary.textContent = `이 구간 합계 — 활성 ${formatDuration(sum(series, "active_seconds"))} / 총 ${formatDuration(total)}`;

  // 가장 많이 쓴 칸을 기준으로 막대 폭을 정한다(칸 길이 전체가 기준이면 대부분 짤막하다).
  const maxTotal = Math.max(...series.buckets.map((b) => b.total_seconds));

  const chart = document.createElement("div");
  chart.className = "bucket-chart";
  for (const bucket of series.buckets) {
    const label = document.createElement("span");
    label.className = "bucket-chart-label";
    const text = formatBucketLabel(unit, {
      start: new Date(bucket.start),
      end: new Date(bucket.end),
    });
    label.textContent = text;
    chart.append(
      createUsageRow({
        label,
        usage: bucket,
        maxTotal,
        description: text,
      }),
    );
  }

  container.append(summary, createUsageLegend(), chart);
  return container;
}
