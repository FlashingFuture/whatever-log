import {
  fetchGoals,
  fetchSiteUsage,
  fetchUsage,
  type Goal,
  type SiteRangeUsage,
} from "../api";
import { createGoalManager } from "../components/goals/GoalManager";
import { createPeriodView } from "../components/period/PeriodView";
import {
  createSiteUsageList,
  createSiteUsageUnavailable,
} from "../components/usage/SiteUsageList";
import { createUsageChart } from "../components/usage/UsageChart";
import {
  domainsByBrowser,
  goalProcessRows,
  goalSiteRows,
} from "../lib/goalOverview";
import { formatTarget, formatWeekdays } from "../lib/goalText";
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

/** 브라우저 한 곳에서 연결한 도메인들의 사용량. 못 불러와도 프로세스 차트는 그대로 보이게, 이 자리만 안내로 바꾼다. */
async function siteSection(
  browser: string,
  domains: string[],
  period: { start: Date; end: Date },
): Promise<HTMLElement> {
  let usage: SiteRangeUsage;
  try {
    usage = await fetchSiteUsage(browser, period.start, period.end);
  } catch {
    return createSiteUsageUnavailable();
  }
  const section = createSiteUsageList({
    ...usage,
    by_site: goalSiteRows(domains, usage.by_site),
  });
  section.classList.add(styles.sites);
  return section;
}

/**
 * 목표 개요 화면(`#/goal/<id>`): 목표 이름과 설명, 홈과 같은 일/주/월 선택과 구간 이동, 그 아래에 이 목표에 연결한 프로세스별 사용량(홈의 차트와 같은
 * 컴포넌트, 활성 시간순, 기록이 없는 연결 프로세스는 0)과 연결한 사이트별 사용량. 새 집계는 없다 — `/api/usage`와 `/api/sites`의 응답에서 연결한
 * 것만 골라 보여 준다(docs/goal-management.md). 읽기 전용이고, 연결을 바꾸는 일은 목표 관리 모달이 한다. 돌려주는 함수로 화면을 정리한다.
 */
export function mountGoalPage(root: HTMLElement, goalId: number): () => void {
  // 모달에서 연결을 바꾸면 이 화면을 다시 불러온다.
  const manager = createGoalManager({
    onChange: () => view.refresh(),
    onClose: () =>
      root.querySelector<HTMLElement>("[data-goal-connections]")?.focus(),
  });

  const header = document.createElement("div");
  const title = document.createElement("h1");
  title.className = styles.title;
  const meta = document.createElement("p");
  meta.className = styles.meta;
  const connections = document.createElement("button");
  connections.type = "button";
  connections.className = styles.manage;
  connections.dataset.goalConnections = "";
  connections.textContent = "프로세스 연결 관리";
  connections.addEventListener("click", () => manager.openDetail(goalId));
  header.hidden = true;
  header.append(title, meta, connections);

  const view = createPeriodView({
    loadContent: async (period) => {
      const [goals, usage] = await Promise.all([
        fetchGoals(),
        fetchUsage(period.start, period.end),
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

      const page = document.createElement("div");
      if (goal.processes.length === 0 && goal.sites.length === 0) {
        page.append(
          paragraph(
            "연결한 프로세스나 사이트가 없어요. 위의 ‘프로세스 연결 관리’에서 연결해 보세요.",
            styles.notice,
          ),
        );
        return page;
      }

      if (goal.processes.length > 0) {
        page.append(
          createUsageChart({
            ...usage,
            by_process: goalProcessRows(goal.processes, usage.by_process),
          }),
        );
      }
      for (const [browser, domains] of domainsByBrowser(goal.sites)) {
        page.append(await siteSection(browser, domains, period));
      }
      return page;
    },
  });

  root.replaceChildren(header, view.element);
  return () => {
    view.destroy();
    manager.destroy();
  };
}
