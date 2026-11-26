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

/** 칸들을 모두 더한 구간의 사용 시간(프로세스 상세 왼쪽 요약에 쓴다). */
export function seriesTotals(series: ProcessSeries): UsageNumbers {
  const totals: UsageNumbers = {
    active_seconds: 0,
    idle_seconds: 0,
    background_seconds: 0,
    total_seconds: 0,
  };
  for (const bucket of series.buckets) {
    totals.active_seconds += bucket.active_seconds;
    totals.idle_seconds += bucket.idle_seconds;
    totals.background_seconds += bucket.background_seconds;
    totals.total_seconds += bucket.total_seconds;
  }
  return totals;
}

/** 라벨을 감추는 단계에 쓰는 클래스: 단위(칸 수가 다르다)와, 하나 건너 하나·넷에 하나만 남길 때 감출 칸인지. */
function labelClasses(unit: PeriodUnit, index: number): string[] {
  const classes = [styles.label, styles[unit]];
  if (index % 2 === 1) {
    classes.push(styles.odd);
  }
  if (index % 4 !== 0) {
    classes.push(styles.offFour);
  }
  return classes;
}

/**
 * 시간 칸 하나: 세로 막대 + 짧은 라벨(`01:00`, `11/03`). 칸이 좁아 수치는 글자로 늘어놓지 않고
 * 막대의 툴팁·스크린 리더(전체 라벨 + 활성/유휴/백그라운드/총)로 준다.
 * 차트가 좁으면 라벨을 하나 건너 하나(더 좁으면 넷에 하나)만 남긴다(labelClasses) — 감춘 라벨도 자리는 남아 막대 높이는 그대로다.
 */
function createBucketColumn(
  usage: UsageNumbers,
  maxTotal: number,
  fullLabel: string,
  shortLabel: string,
  labelClassNames: string[],
): HTMLElement {
  const column = document.createElement("div");
  column.className = styles.column;
  const breakdown =
    `${fullLabel}: 활성 ${formatDuration(usage.active_seconds)}, ` +
    `유휴 ${formatDuration(usage.idle_seconds)}, ` +
    `백그라운드 ${formatDuration(usage.background_seconds)}, ` +
    `총 ${formatDuration(usage.total_seconds)}`;
  // 막대는 색으로만 구분되므로 수치를 텍스트로도 준다. 툴팁은 막대에만 둔다(라벨 위에서는 뜨지 않는다).
  const bar = createUsageBar(usage, maxTotal);
  bar.classList.add(styles.bar);
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", breakdown);
  bar.title = breakdown;

  // 짧은 라벨은 막대의 이름(전체 라벨)에 이미 들어 있어 스크린 리더에는 숨긴다.
  const label = document.createElement("span");
  label.className = labelClassNames.join(" ");
  label.setAttribute("aria-hidden", "true");
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

  if (seriesTotals(series).total_seconds === 0) {
    const empty = document.createElement("p");
    empty.className = styles.empty;
    empty.textContent = "이 구간에는 기록된 사용 내역이 없습니다.";
    container.append(empty);
    return container;
  }

  // 가장 많이 쓴 칸을 기준으로 막대 높이를 정한다(칸 길이 전체가 기준이면 대부분 짤막하다).
  const maxTotal = maxOf(series.buckets, (b) => b.total_seconds);
  const columns = series.buckets.map((usage, index) =>
    createBucketColumn(
      usage,
      maxTotal,
      formatBucketLabel(unit, buckets[index]),
      formatBucketShortLabel(unit, buckets[index]),
      labelClasses(unit, index),
    ),
  );

  container.append(createColumnChart(columns, "", { spacing: "compact" }));
  return container;
}
