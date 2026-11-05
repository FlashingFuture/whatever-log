import type { GoalProgressResponse, RangeUsage } from "../../api";
import { formatDuration } from "../../lib/format";
import { chooseTopBlocks, type TopProcess } from "../../lib/goalSummary";
import { createRouteLink } from "../../router/router";
import { createProcessIcon, createSiteIcon } from "./ProcessIcon";
import styles from "./UsageSummary.module.css";

export interface UsageSummaryProps {
  usage: RangeUsage;
  /** 구간의 목표 수행 시간. 불러오지 못했으면 null(목표 칸만 "-"로 보인다). */
  progress: GoalProgressResponse | null;
  /** "목표 프로세스 관리"를 눌렀다. */
  onManageGoals: () => void;
}

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

function text(value: string): HTMLSpanElement {
  const span = document.createElement("span");
  span.textContent = value;
  return span;
}

function processStat(label: string, top: TopProcess | null): HTMLElement {
  if (top === null) {
    return stat(label, text("-"));
  }
  // 사이트면 도메인을 이름으로, 그 사이트를 본 브라우저는 시간 옆에 덧붙인다. 눌러서 가는 곳은 브라우저 상세다.
  const shown = top.site ?? top.process;
  const link = createRouteLink({ name: "process", process: top.process });
  link.className = styles.top;
  link.title = top.site ? `${top.site} · ${top.process}` : top.process;
  const name = document.createElement("span");
  name.className = styles.topName;
  name.textContent = shown; // OS·웹에서 온 값이라 textContent로 넣는다
  link.append(
    top.site ? createSiteIcon(top.site) : createProcessIcon(top.process),
    name,
  );
  return stat(
    label,
    link,
    top.site
      ? `${formatDuration(top.active_seconds)} · ${top.process}`
      : formatDuration(top.active_seconds),
  );
}

/**
 * 홈 왼쪽 요약: 목표 수행 시간, 가장 길게 수행한 프로세스(목표 중 / 실제), 그 아래 목표 관리 링크.
 * 값은 모두 서버가 계산한 것(목표 수행은 packages/goals, 실제는 packages/aggregation)을 그대로
 * 보여 주고, 화면은 둘이 같은 프로세스인지만 보아 하나로 합친다.
 */
export function createUsageSummary(props: UsageSummaryProps): HTMLElement {
  const container = document.createElement("section");
  container.className = styles.summary;
  container.setAttribute("aria-label", "요약");

  const { progress, usage } = props;
  container.append(
    stat(
      "목표 수행 시간",
      text(progress ? formatDuration(progress.summary.active_seconds) : "-"),
    ),
  );

  const blocks = chooseTopBlocks(
    progress?.summary.top ?? null,
    usage.summary.top,
  );
  if (blocks.kind === "same") {
    container.append(processStat("가장 길게 수행한 프로세스", blocks.top));
  } else if (blocks.kind === "goalAndActual") {
    container.append(
      processStat("목표 중 가장 길게 수행한 프로세스", blocks.goalTop),
      processStat("실제 가장 길게 수행한 프로세스", blocks.actualTop),
    );
  } else {
    container.append(
      processStat("실제 가장 길게 수행한 프로세스", blocks.actualTop),
    );
  }

  const manage = document.createElement("button");
  manage.type = "button";
  manage.className = styles.manage;
  manage.dataset.goalManage = "";
  manage.textContent = "목표 프로세스 관리";
  manage.addEventListener("click", props.onManageGoals);
  container.append(manage);
  return container;
}
