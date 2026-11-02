import type { RangeUsage } from "../api";
import { formatDuration } from "../format";
import { createRouteLink } from "../router";
import { summarizeUsage } from "../summary";
import { createProcessIcon } from "./ProcessIcon";
import styles from "./UsageSummary.module.css";

function stat(label: string, value: Node, detail?: string): HTMLElement {
  const block = document.createElement("div");
  block.className = styles.stat;

  const labelElement = document.createElement("div");
  labelElement.className = styles.label;
  labelElement.textContent = label;

  const valueElement = document.createElement("div");
  valueElement.className = styles.value;
  valueElement.append(value);

  block.append(labelElement, valueElement);
  if (detail) {
    const detailElement = document.createElement("div");
    detailElement.className = styles.detail;
    detailElement.textContent = detail;
    block.append(detailElement);
  }
  return block;
}

/**
 * 홈 왼쪽 요약: 구간의 총 사용 시간과 가장 많이 쓴 프로그램. 둘 다 집중(active) 시간
 * 기준이다(계산은 summary.ts).
 */
export function createUsageSummary(usage: RangeUsage): HTMLElement {
  const container = document.createElement("section");
  container.className = styles.summary;
  container.setAttribute("aria-label", "요약");

  const { activeSeconds, idleSeconds, top } = summarizeUsage(usage.by_process);
  const total = document.createElement("span");
  total.textContent = formatDuration(activeSeconds);

  const topValue = document.createElement("span");
  if (top) {
    const link = createRouteLink({ name: "process", process: top.process });
    link.className = styles.top;
    link.title = top.process;
    const name = document.createElement("span");
    name.className = styles.topName;
    name.textContent = top.process; // OS에서 온 값이라 textContent로 넣는다
    link.append(createProcessIcon(top.process), name);
    topValue.append(link);
  } else {
    topValue.textContent = "-";
  }

  container.append(
    stat(
      "총 사용 시간",
      total,
      idleSeconds > 0
        ? `유휴 포함 ${formatDuration(activeSeconds + idleSeconds)}`
        : undefined,
    ),
    stat(
      "가장 많이 사용한 프로그램",
      topValue,
      top ? formatDuration(top.active_seconds) : undefined,
    ),
  );
  return container;
}
