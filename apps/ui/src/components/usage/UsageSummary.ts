import type {
  GoalProgress,
  GoalProgressResponse,
  GoalTotals,
  RangeUsage,
} from "../../api";
import { formatDuration } from "../../lib/format";
import {
  type Achievement,
  achievement,
  timePair,
} from "../../lib/goalSelection";
import { chooseTopBlocks, type TopProcess } from "../../lib/goalSummary";
import { createRouteLink } from "../../router/router";
import { createProcessIcon, createSiteIcon } from "./ProcessIcon";
import type { UsageNumbers } from "./UsageRow";
import styles from "./UsageSummary.module.css";

export interface UsageSummaryProps {
  usage: RangeUsage;
  /** 구간의 목표 수행 시간. 불러오지 못했으면 null(목표 칸만 "-"로 보인다). */
  progress: GoalProgressResponse | null;
  /** 목표별 모든 기기의 합계. 받지 못했으면 null(전체 칸만 "-"로 보인다). */
  totals: GoalTotals | null;
  /** 고른 목표(null = 목표 전체). 지금 목록에 있는 것이어야 한다 — 호출부가 먼저 정리한다. */
  selectedGoalId: number | null;
  /** 관리 링크("목표 프로세스 관리")를 눌렀다. */
  onManageGoals: () => void;
  /** 관리 링크의 글자. 홈은 "목표 프로세스 관리", 목표 개요는 "프로세스 연결 관리". */
  manageLabel?: string;
}

/** 요약의 한 칸: 흐린 라벨, 큰 값, (있으면) 흐린 설명. 홈 요약과 프로세스 상세 요약이 같이 쓴다. */
export function createStat(
  label: string,
  value: Node,
  detail?: string,
): HTMLElement {
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
    return createStat(label, text("-"));
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
  return createStat(
    label,
    link,
    top.site
      ? `${formatDuration(top.active_seconds)} · ${top.process}`
      : formatDuration(top.active_seconds),
  );
}

/** 한 쪽의 "라벨 시간"(예: 전체 1시간 15분). 시간은 굵게, 라벨은 흐리게. */
function timePart(label: string, seconds: number | null): HTMLElement {
  const part = document.createElement("span");
  part.className = styles.timePart;
  const labelElement = document.createElement("span");
  labelElement.className = styles.timeLabel;
  labelElement.textContent = label;
  const value = document.createElement("span");
  value.className = styles.timeValue;
  value.textContent = seconds === null ? "-" : formatDuration(seconds);
  part.append(labelElement, " ", value);
  return part;
}

/** `라벨 시간 | 라벨 시간` 한 줄(예: 전체 1시간 | 현 기기 30분). 좁으면 칸 사이에서 줄이 바뀐다. 시간을 모르면 null("-"). */
export function createTimePair(
  parts: readonly { label: string; seconds: number | null }[],
): HTMLElement {
  const value = document.createElement("span");
  value.className = styles.timePair;
  parts.forEach((part, index) => {
    if (index > 0) {
      const separator = document.createElement("span");
      separator.className = styles.timeSeparator;
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = "|";
      value.append(separator);
    }
    value.append(timePart(part.label, part.seconds));
  });
  return value;
}

/** 요약 맨 아래의 링크 모양 버튼(홈의 "목표 프로세스 관리", 상세의 "프로세스 연결"). */
export function createSummaryAction(
  label: string,
  onClick: () => void,
): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = styles.manage;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

/**
 * "목표 수행 시간"의 값: `전체 xx분 | 현 기기 xx분`. 전체는 모든 기기를 더한 것이고 현 기기는 이 PC의 것이다. 전체를 알 수 없으면
 * (합계를 받지 못함) 전체 칸만 "-"다.
 */
function timeValue(
  goals: readonly GoalProgress[],
  selectedId: number | null,
  totals: GoalTotals | null,
): HTMLElement {
  const pair = timePair(goals, selectedId, totals);
  return createTimePair([
    { label: "전체", seconds: pair.total },
    { label: "현 기기", seconds: pair.device },
  ]);
}

/**
 * 달성률 블록: 큰 퍼센트, 막대(100%에서 멈춘다 — 넘친 만큼은 글자로 보인다), 목표량 대비 수행 시간. 구간에 목표를 적용하는 날이 없으면 "-"와
 * 이유만 보인다. 분자가 이 PC만의 값이면(전체를 못 받음) 그렇다고 적는다.
 */
function achievementBlock(rate: Achievement | null): HTMLElement {
  const block = createStat(
    "달성률",
    text(rate === null ? "-" : `${rate.percent}%`),
    rate === null
      ? "이 구간에는 목표를 적용하는 날이 없어요."
      : `목표 ${formatDuration(rate.targetSeconds)} 중 ${formatDuration(rate.achievedSeconds)}${rate.basis === "device" ? " · 현 기기 기준" : ""}`,
  );
  if (rate !== null) {
    const track = document.createElement("div");
    track.className = styles.rateTrack;
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", "달성률");
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(Math.min(100, rate.percent)));
    track.setAttribute("aria-valuetext", `${rate.percent}%`);
    const fill = document.createElement("div");
    fill.className = styles.rateFill;
    fill.style.width = `${Math.min(100, Math.max(0, rate.percent))}%`;
    track.append(fill);
    block.children[1]?.after(track); // 퍼센트 바로 아래, 설명 위
  }
  return block;
}

/** 고른 목표에 연결한 프로세스·사이트와 각각의 수행 시간(긴 것부터). 수행한 것이 없으면 안내만 보인다. */
function goalBreakdown(goal: GoalProgress): HTMLElement {
  const targets: TopProcess[] = [
    ...goal.processes.map((item) => ({
      process: item.process,
      active_seconds: item.active_seconds,
    })),
    ...goal.sites.map((item) => ({
      process: item.browser,
      active_seconds: item.active_seconds,
      site: item.domain,
    })),
  ]
    .filter((target) => target.active_seconds > 0)
    .sort((a, b) => b.active_seconds - a.active_seconds);

  const block = document.createElement("div");
  block.className = styles.stat;
  const label = document.createElement("div");
  label.className = styles.label;
  label.textContent = "연결한 프로세스·사이트";
  block.append(label);
  if (targets.length === 0) {
    const empty = document.createElement("div");
    empty.className = styles.detail;
    empty.textContent = "이 구간에는 수행한 기록이 없어요.";
    block.append(empty);
    return block;
  }
  const list = document.createElement("ul");
  list.className = styles.targets;
  for (const target of targets) {
    const item = document.createElement("li");
    item.className = styles.target;
    const link = createRouteLink({ name: "process", process: target.process });
    link.className = styles.top;
    link.title = target.site
      ? `${target.site} · ${target.process}`
      : target.process;
    const text = document.createElement("span");
    text.className = styles.topName;
    text.textContent = target.site ?? target.process; // OS·웹에서 온 값이라 textContent로 넣는다
    link.append(
      target.site
        ? createSiteIcon(target.site)
        : createProcessIcon(target.process),
      text,
    );
    const time = document.createElement("span");
    time.className = styles.targetTime;
    time.textContent = formatDuration(target.active_seconds);
    item.append(link, time);
    list.append(item);
  }
  block.append(list);
  return block;
}

/**
 * 홈 왼쪽 요약: 목표 수행 시간(`전체 | 현 기기`), 달성률, 가장 길게 수행한 프로세스(목표 중 / 실제),
 * 그 아래 목표 관리 링크(목표를 고르는 단추는 요약 위, 페이지 맨 위에 있다). 목표 하나를 고르면 그 목표의 시간과, 연결한 프로세스·사이트별 수행 시간을 보인다.
 * 값은 모두 서버가 계산한 것(목표 수행은 packages/goals, 실제는 packages/aggregation)을 그대로
 * 보여 주고, 화면은 둘이 같은 프로세스인지만 보아 하나로 합친다.
 */
export function createUsageSummary(props: UsageSummaryProps): HTMLElement {
  const container = document.createElement("section");
  container.className = styles.summary;
  container.setAttribute("aria-label", "요약");

  const { progress, usage } = props;
  const selectedGoal =
    progress?.goals.find((goal) => goal.id === props.selectedGoalId) ?? null;
  if (progress === null) {
    container.append(createStat("목표 수행 시간", text("-")));
  } else if (selectedGoal !== null) {
    container.append(
      createStat(
        "목표 수행 시간",
        timeValue(progress.goals, selectedGoal.id, props.totals),
      ),
      achievementBlock(
        achievement(progress.goals, selectedGoal.id, props.totals),
      ),
      goalBreakdown(selectedGoal),
    );
  } else {
    container.append(
      createStat(
        "목표 수행 시간",
        timeValue(progress.goals, null, props.totals),
      ),
      achievementBlock(achievement(progress.goals, null, props.totals)),
    );
  }

  const blocks = chooseTopBlocks(
    progress?.summary.top ?? null,
    usage.summary.top,
  );
  if (selectedGoal !== null) {
    // 목표 하나를 보는 중에는 위의 "연결한 프로세스·사이트"가 그 목표에서 가장 길게 수행한 것까지 보여 준다
  } else if (blocks.kind === "same") {
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

  const manage = createSummaryAction(
    props.manageLabel ?? "목표 프로세스 관리",
    props.onManageGoals,
  );
  manage.dataset.goalManage = "";
  container.append(manage);
  return container;
}

export interface ProcessSummaryProps {
  /** 고른 구간에서 이 프로세스의 사용 시간(칸을 모두 더한 것). */
  usage: UsageNumbers;
  /** "프로세스 연결"을 눌렀다(목표 목록 팝업을 연다). */
  onLinkGoal: () => void;
}

/**
 * 프로세스 상세 왼쪽 요약: 고른 구간의 사용 시간(`활성 | 총`, 아래에 유휴·백그라운드)과 그 아래 "프로세스 연결"(이 프로세스를 목표에 연결).
 * 홈 요약과 같은 칸 모양을 쓴다.
 */
export function createProcessSummary(props: ProcessSummaryProps): HTMLElement {
  const container = document.createElement("section");
  container.className = styles.summary;
  container.setAttribute("aria-label", "요약");
  const { usage } = props;
  const link = createSummaryAction("프로세스 연결", props.onLinkGoal);
  link.dataset.processLink = "";
  container.append(
    createStat(
      "사용 시간",
      createTimePair([
        { label: "활성", seconds: usage.active_seconds },
        { label: "총", seconds: usage.total_seconds },
      ]),
      `유휴 ${formatDuration(usage.idle_seconds)} · 백그라운드 ${formatDuration(usage.background_seconds)}`,
    ),
    link,
  );
  return container;
}
