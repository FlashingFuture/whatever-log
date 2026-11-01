import type { ProcessSeries } from "../api";
import { formatDuration } from "../format";
import { type Bucket, formatBucketLabel, type PeriodUnit } from "../period";
import styles from "./BucketChart.module.css";
import { createUsageLegend } from "./UsageLegend";
import { createUsageRow } from "./UsageRow";

function sum(series: ProcessSeries, field: "active_seconds" | "total_seconds") {
  return series.buckets.reduce((total, bucket) => total + bucket[field], 0);
}

/**
 * 한 프로세스의 칸별(일: 시간, 주/월: 날짜) 사용 시간. 홈의 프로세스 목록과 같은
 * 줄 모양을 쓰되, 줄이 프로세스가 아니라 시간 칸이다. 칸마다 한 줄씩 위에서
 * 아래로 늘어놓고, 기록이 없는 칸도 빈 막대로 남겨 시간의 흐름이 이어져 보이게 한다.
 *
 * buckets는 요청에 쓴 칸(클라이언트가 계산한 것)이고 series.buckets와 같은 순서·개수다
 * — 라벨은 서버가 돌려준 시각이 아니라 이 칸으로 만든다.
 */
export function createBucketChart(
  unit: PeriodUnit,
  series: ProcessSeries,
  buckets: Bucket[],
): HTMLElement {
  const container = document.createElement("div");

  const total = sum(series, "total_seconds");
  if (total === 0) {
    const empty = document.createElement("p");
    empty.className = styles.empty;
    empty.textContent = "이 구간에는 기록된 사용 내역이 없습니다.";
    container.append(empty);
    return container;
  }

  const summary = document.createElement("p");
  summary.className = styles.summary;
  summary.textContent = `이 구간 합계 — 활성 ${formatDuration(sum(series, "active_seconds"))} / 총 ${formatDuration(total)}`;

  // 가장 많이 쓴 칸을 기준으로 막대 폭을 정한다(칸 길이 전체가 기준이면 대부분 짤막하다).
  const maxTotal = Math.max(...series.buckets.map((b) => b.total_seconds));

  const chart = document.createElement("div");
  chart.className = styles.chart;
  series.buckets.forEach((usage, index) => {
    const label = document.createElement("span");
    label.className = styles.label;
    const text = formatBucketLabel(unit, buckets[index]);
    label.textContent = text;
    chart.append(createUsageRow({ label, usage, maxTotal, description: text }));
  });

  container.append(summary, createUsageLegend(), chart);
  return container;
}
