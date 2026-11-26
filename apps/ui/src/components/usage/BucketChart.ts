import type { ProcessSeries } from "../../api";
import { formatDuration } from "../../lib/format";
import {
  type Bucket,
  formatBucketLabel,
  formatBucketShortLabel,
  type PeriodUnit,
} from "../../lib/period";
import { maxOf } from "../../lib/stats";
import styles from "./BucketChart.module.css";
import { createUsageBar } from "./UsageBar";
import { createColumnChart } from "./UsageChart";
import type { UsageNumbers } from "./UsageRow";

function sum(series: ProcessSeries, field: "active_seconds" | "total_seconds") {
  return series.buckets.reduce((total, bucket) => total + bucket[field], 0);
}

/**
 * 시간 칸 하나: 세로 막대 + 짧은 라벨(`01:00`, `11/03`). 칸이 좁아 수치는 글자로 늘어놓지 않고
 * 툴팁·스크린 리더(전체 라벨 + 활성/유휴/백그라운드/총)로 준다.
 * 칸이 많으면(일·월) 하나 건너 하나의 라벨은 좁은 화면에서 감춘다(minor) — 자리는 남겨 막대 높이는 그대로다.
 */
function createBucketColumn(
  usage: UsageNumbers,
  maxTotal: number,
  fullLabel: string,
  shortLabel: string,
  minorLabel: "day" | "month" | null,
): HTMLElement {
  const column = document.createElement("div");
  column.className = styles.column;
  const breakdown =
    `${fullLabel}: 활성 ${formatDuration(usage.active_seconds)}, ` +
    `유휴 ${formatDuration(usage.idle_seconds)}, ` +
    `백그라운드 ${formatDuration(usage.background_seconds)}, ` +
    `총 ${formatDuration(usage.total_seconds)}`;
  // 막대는 색으로만 구분되므로 수치를 텍스트로도 준다.
  column.setAttribute("role", "img");
  column.setAttribute("aria-label", breakdown);
  column.title = breakdown;

  const bar = createUsageBar(usage, maxTotal);
  bar.classList.add(styles.bar);

  const label = document.createElement("span");
  label.className = styles.label;
  if (minorLabel === "day") {
    label.classList.add(styles.minorDay);
  } else if (minorLabel === "month") {
    label.classList.add(styles.minorMonth);
  }
  label.textContent = shortLabel;

  column.append(bar, label);
  return column;
}

/**
 * 한 프로세스의 칸별(일: 시간, 주/월: 날짜) 사용 시간을 세로 막대로 왼쪽에서 오른쪽으로 늘어놓는다(홈 차트와 같은 막대,
 * 칸은 좁게 — 구간 전체가 한 눈에 들어온다). 기록이 없는 칸도 빈 막대로 남겨 시간의 흐름이 이어져 보이게 한다.
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
  container.className = styles.container;

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

  // 가장 많이 쓴 칸을 기준으로 막대 높이를 정한다(칸 길이 전체가 기준이면 대부분 짤막하다).
  const maxTotal = maxOf(series.buckets, (b) => b.total_seconds);
  // 주(7칸)는 라벨이 다 들어간다. 일(24칸)·월(28~31칸)은 좁은 화면에서 하나 건너 하나만 보인다.
  const minor = unit === "week" ? null : unit;
  const columns = series.buckets.map((usage, index) =>
    createBucketColumn(
      usage,
      maxTotal,
      formatBucketLabel(unit, buckets[index]),
      formatBucketShortLabel(unit, buckets[index]),
      index % 2 === 1 ? minor : null,
    ),
  );

  container.append(
    summary,
    createColumnChart(columns, "", { spacing: "compact" }),
  );
  return container;
}
