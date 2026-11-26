import type { RangeUsage } from "../../api";
import { maxOf } from "../../lib/stats";
import { createProcessColumn } from "./ProcessColumn";
import styles from "./UsageChart.module.css";
import { createUsageLegend } from "./UsageLegend";

/** 구간의 프로세스별 사용 시간 막대 차트. 어떤 구간인지(제목/라벨)는 호출부가 그린다. */
export function createUsageChart(usage: RangeUsage): HTMLElement {
  // 가장 오래 떠 있던(total) 프로세스를 기준으로 막대 높이를 정한다 — 구간
  // 전체 길이(하루/한 주/한 달)를 기준으로 하면 거의 모든 막대가 짤막해져서
  // 비교가 어렵다. 칸 순서는 집중(active) 시간순이라(서버 정렬, 왼쪽 위부터), 막대 높이
  // (전체 시간)와 순서가 다를 수 있다.
  const maxTotal = maxOf(usage.by_process, (row) => row.total_seconds);

  return createColumnChart(
    usage.by_process.map((row) => createProcessColumn(row, maxTotal)),
    "기록된 사용 내역이 없습니다.",
  );
}

/**
 * 칸 사이 간격과 칸 폭.
 * - regular: 넓은 칸(이름·아이콘·시간이 들어가는 홈·목표 개요). 넘치면 옆으로 스크롤한다.
 * - compact: 좁은 칸(라벨 한 줄만 있는 프로세스 상세의 시간 칸). 칸이 화면 폭을 나눠 가져 한 눈에 들어온다.
 */
export type ColumnSpacing = "regular" | "compact";

export interface ColumnChartOptions {
  spacing?: ColumnSpacing;
}

/** 이미 만든 칸들을 범례와 함께 한 줄로 늘어놓는다(홈·목표 개요·프로세스 상세가 같이 쓴다). 칸이 없으면 emptyText를 보인다. */
export function createColumnChart(
  columns: readonly HTMLElement[],
  emptyText: string,
  options: ColumnChartOptions = {},
): HTMLElement {
  const container = document.createElement("div");
  if (columns.length === 0) {
    const empty = document.createElement("p");
    empty.className = styles.empty;
    empty.textContent = emptyText;
    container.append(empty);
    return container;
  }
  const chart = document.createElement("div");
  chart.className = `${styles.chart} ${options.spacing === "compact" ? styles.compact : styles.regular}`;
  chart.append(...columns);
  container.append(createUsageLegend(), chart);
  return container;
}
