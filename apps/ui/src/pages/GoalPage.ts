import {
  fetchGoalProgress,
  fetchGoals,
  fetchGoalTotals,
  fetchSiteUsage,
  fetchUsage,
  type Goal,
  type SiteUsage,
} from "../api";
import { createGoalManager } from "../components/goals/GoalManager";
import { createPeriodView } from "../components/period/PeriodView";
import { createUsageColumn } from "../components/usage/ProcessColumn";
import {
  createProcessIcon,
  createSiteIcon,
} from "../components/usage/ProcessIcon";
import { createColumnChart } from "../components/usage/UsageChart";
import { createUsageSummary } from "../components/usage/UsageSummary";
import {
  domainsByBrowser,
  type GoalTarget,
  goalProcessRows,
  goalSiteRows,
  goalTargets,
} from "../lib/goalOverview";
import { dayRange } from "../lib/goalSelection";
import { formatTarget, formatWeekdays } from "../lib/goalText";
import { maxOf } from "../lib/stats";
import { createRouteLink, HOME } from "../router/router";
import styles from "./GoalPage.module.css";

function paragraph(text: string, className: string): HTMLParagraphElement {
  const element = document.createElement("p");
  element.className = className;
  element.textContent = text;
  return element;
}

/** "하루 2시간 · 평일 · 프로세스 3개 · 사이트 1개" */
function describe(goal: Goal): string {
  const links = [
    goal.processes.length > 0 ? `프로세스 ${goal.processes.length}개` : "",
    goal.sites.length > 0 ? `사이트 ${goal.sites.length}개` : "",
  ].filter(Boolean);
  return [
    `하루 ${formatTarget(goal.daily_target_minutes)}`,
    formatWeekdays(goal.weekdays),
    links.length === 0 ? "연결된 프로세스 없음" : links.join(" · "),
  ].join(" · ");
}

/** 칸 하나. 사이트는 사이트 아이콘에 그 사이트를 연 브라우저 아이콘을 작게 겹쳐 붙이고, 누르면 그 브라우저의 상세로 간다. */
function columnOf(target: GoalTarget, maxTotal: number): HTMLElement {
  if (target.kind === "process") {
    return createUsageColumn(
      {
        name: target.process,
        fullName: target.process,
        usage: target.usage,
        icon: createProcessIcon(target.process),
        route: { name: "process", process: target.process },
      },
      maxTotal,
    );
  }
  return createUsageColumn(
    {
      name: target.domain,
      fullName: `${target.domain} (${target.browser})`,
      usage: target.usage,
      icon: createSiteIcon(target.domain),
      badge: createProcessIcon(target.browser),
      route: { name: "process", process: target.browser },
    },
    maxTotal,
  );
}

interface SiteResult {
  rows: (SiteUsage & { browser: string })[];
  /** 사이트 정보를 받지 못한 브라우저들(그 브라우저의 사이트 칸은 그리지 않는다 — 0으로 그리면 "안 썼다"로 읽힌다). */
  failed: string[];
}

/** 연결한 브라우저마다 그 구간의 사이트별 사용량을 받아 연결한 도메인만 고른다. 한 브라우저가 실패해도 나머지는 그대로 보인다. */
async function loadSites(
  goal: Goal,
  period: { start: Date; end: Date },
): Promise<SiteResult> {
  const result: SiteResult = { rows: [], failed: [] };
  const grouped = [...domainsByBrowser(goal.sites)];
  await Promise.all(
    grouped.map(async ([browser, domains]) => {
      try {
        const usage = await fetchSiteUsage(browser, period.start, period.end);
        result.rows.push(
          ...goalSiteRows(domains, usage.by_site).map((row) => ({
            ...row,
            browser,
          })),
        );
      } catch {
        result.failed.push(browser);
      }
    }),
  );
  // 요청이 끝나는 순서와 상관없이 연결한 순서(브라우저, 도메인)로 고정해 같은 결과가 나오게 한다.
  const order = new Map(grouped.map(([browser], index) => [browser, index]));
  result.rows.sort(
    (a, b) => (order.get(a.browser) ?? 0) - (order.get(b.browser) ?? 0),
  );
  return result;
}

/**
 * 목표 개요 화면(`#/goal/<id>`): 홈과 같은 구조 — 위에 목표 이름과 설명, 그 아래 일/주/월 선택과 구간 이동, 왼쪽에 이 목표의 요약(수행 시간 `전체 | 현 기기`·
 * 달성률·연결한 프로세스·사이트별 시간·"프로세스 연결 관리"), 오른쪽에 연결한 프로세스와 **사이트**별 막대 차트. 브라우저는 통째로 한 칸이 아니라
 * 연결한 사이트마다 한 칸이고(브라우저 아이콘이 겹쳐 붙는다), 그래서 지정한 실제 사이트끼리 비교된다. 홈은 그대로 브라우저 한 칸이다.
 * 새 집계는 없다 — `/api/usage`·`/api/sites`·`/api/goals/progress`의 응답에서 연결한 것만 골라 보여 준다(docs/goal-management.md).
 * 돌려주는 함수로 화면을 정리한다.
 */
export function mountGoalPage(root: HTMLElement, goalId: number): () => void {
  // 모달에서 연결을 바꾸면 이 화면을 다시 불러온다.
  const manager = createGoalManager({
    onChange: () => view.refresh(),
    // 15초마다 요약이 다시 그려져 열었던 링크가 사라졌을 수 있다 — 지금 있는 링크로 포커스를 돌려준다.
    onClose: () =>
      root.querySelector<HTMLElement>("[data-goal-manage]")?.focus(),
  });

  const header = document.createElement("div");
  const title = document.createElement("h1");
  title.className = styles.title;
  const meta = document.createElement("p");
  meta.className = styles.meta;
  header.hidden = true;
  header.append(title, meta);

  const view = createPeriodView({
    loadContent: async (period) => {
      const { from, to } = dayRange(period.start, period.end);
      const [goals, usage, progress, totals] = await Promise.all([
        fetchGoals(),
        fetchUsage(period.start, period.end),
        // 요약을 못 불러와도 사용량은 보여 준다(홈과 같은 규칙).
        fetchGoalProgress(period.start, period.end).catch(() => null),
        fetchGoalTotals(from, to).catch(() => null),
      ]);
      const goal = goals.find((candidate) => candidate.id === goalId);
      if (goal === undefined) {
        header.hidden = true;
        const missing = document.createElement("div");
        const home = createRouteLink(HOME);
        home.textContent = "홈으로";
        missing.append(
          paragraph(
            "목표를 찾을 수 없어요. 지워졌을 수 있어요.",
            styles.notice,
          ),
          home,
        );
        return missing;
      }
      title.textContent = goal.name; // 사용자가 쓴 글이라 textContent로만 넣는다
      meta.textContent = describe(goal);
      header.hidden = false;

      const sites =
        goal.sites.length > 0
          ? await loadSites(goal, period)
          : { rows: [], failed: [] };
      const targets = goalTargets(
        goalProcessRows(goal.processes, usage.by_process),
        sites.rows,
      );
      const maxTotal = maxOf(targets, (target) => target.usage.total_seconds);

      const side = document.createElement("div");
      side.className = styles.side;
      side.append(
        createUsageSummary({
          usage,
          progress,
          totals,
          selectedGoalId: goal.id,
          onManageGoals: () => manager.openDetail(goal.id),
          manageLabel: "프로세스 연결 관리",
        }),
      );

      const chart = document.createElement("div");
      chart.append(
        createColumnChart(
          targets.map((target) => columnOf(target, maxTotal)),
          "연결한 프로세스나 사이트가 없어요. ‘프로세스 연결 관리’에서 연결해 보세요.",
        ),
      );
      if (sites.failed.length > 0) {
        chart.append(
          paragraph(
            `${sites.failed.join(", ")}의 사이트 정보를 불러오지 못해 그 사이트는 표시하지 못했어요.`,
            styles.warning,
          ),
        );
      }

      const dashboard = document.createElement("div");
      dashboard.className = styles.dashboard;
      dashboard.append(side, chart);
      return dashboard;
    },
  });

  root.replaceChildren(header, view.element);
  return () => {
    view.destroy();
    manager.destroy();
  };
}
