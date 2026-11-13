// 목표 개요 화면에서 "이 목표에 연결한 것만" 골라 나열하는 순수 로직(lib 층). 집계 규칙은 서버가 갖고, 여기는 이미 받은 목록을 거르고 정렬할 뿐이다.

interface UsageNumbers {
  active_seconds: number;
  idle_seconds: number;
  total_seconds: number;
}

export interface ProcessRowLike extends UsageNumbers {
  process: string;
  background_seconds: number;
}

export interface SiteRowLike extends UsageNumbers {
  domain: string;
}

/**
 * 구간의 프로세스별 사용량(서버가 활성 시간순으로 준다)에서 목표에 연결한 프로세스만 골라 그 순서 그대로 둔다.
 * 연결은 했지만 이 구간에 기록이 없는 프로세스는 0으로 뒤에 붙인다(연결한 순서) — "연결했는데 안 켰다"가 보여야 한다.
 */
export function goalProcessRows(
  linked: readonly string[],
  byProcess: readonly ProcessRowLike[],
): ProcessRowLike[] {
  const wanted = new Set(linked);
  const rows = byProcess.filter((row) => wanted.has(row.process));
  const seen = new Set(rows.map((row) => row.process));
  for (const process of linked) {
    if (!seen.has(process)) {
      seen.add(process);
      rows.push({
        process,
        active_seconds: 0,
        idle_seconds: 0,
        background_seconds: 0,
        total_seconds: 0,
      });
    }
  }
  return rows;
}

/**
 * 브라우저 한 곳의 사이트별 사용량에서 목표에 연결한 도메인만 활성 시간순으로 고른다. 기록이 없는 도메인은 0으로 뒤에 붙인다.
 * 서버가 준 순서가 이미 활성 시간순이어도 여기서 다시 정렬해 같은 결과를 보장한다(동률이면 받은 순서 유지).
 */
export function goalSiteRows(
  linkedDomains: readonly string[],
  bySite: readonly SiteRowLike[],
): SiteRowLike[] {
  const wanted = new Set(linkedDomains);
  const rows = bySite
    .filter((row) => wanted.has(row.domain))
    .map((row, index) => ({ row, index }))
    .sort(
      (a, b) =>
        b.row.active_seconds - a.row.active_seconds || a.index - b.index,
    )
    .map(({ row }) => row);
  const seen = new Set(rows.map((row) => row.domain));
  for (const domain of linkedDomains) {
    if (!seen.has(domain)) {
      seen.add(domain);
      rows.push({
        domain,
        active_seconds: 0,
        idle_seconds: 0,
        total_seconds: 0,
      });
    }
  }
  return rows;
}

/** 연결한 사이트를 브라우저별 도메인 목록으로 묶는다(브라우저는 처음 나온 순서). 같은 도메인은 한 번만. */
export function domainsByBrowser(
  sites: readonly { browser: string; domain: string }[],
): Map<string, string[]> {
  const grouped = new Map<string, string[]>();
  for (const site of sites) {
    const domains = grouped.get(site.browser) ?? [];
    if (!domains.includes(site.domain)) {
      domains.push(site.domain);
    }
    grouped.set(site.browser, domains);
  }
  return grouped;
}

interface Numbers {
  active_seconds: number;
  idle_seconds: number;
  background_seconds: number;
  total_seconds: number;
}

/** 목표 개요 차트의 칸 하나: 프로세스, 또는 브라우저 안의 사이트(어느 브라우저인지 함께). */
export type GoalTarget =
  | { kind: "process"; process: string; usage: Numbers }
  | { kind: "site"; browser: string; domain: string; usage: Numbers };

/**
 * 연결한 프로세스와 사이트를 한 목록으로 합쳐 활성 시간이 긴 순서로 놓는다(홈 차트와 같은 기준). 동률이면(기록 없는 0끼리 포함) 프로세스가 먼저고 받은 순서를 지킨다.
 * 사이트는 foreground일 때만 알 수 있어 백그라운드 시간이 없다(0).
 */
export function goalTargets(
  processes: readonly ProcessRowLike[],
  sites: readonly (SiteRowLike & { browser: string })[],
): GoalTarget[] {
  const targets: GoalTarget[] = [
    ...processes.map(
      (row): GoalTarget => ({
        kind: "process",
        process: row.process,
        usage: row,
      }),
    ),
    ...sites.map(
      (row): GoalTarget => ({
        kind: "site",
        browser: row.browser,
        domain: row.domain,
        usage: {
          active_seconds: row.active_seconds,
          idle_seconds: row.idle_seconds,
          background_seconds: 0,
          total_seconds: row.total_seconds,
        },
      }),
    ),
  ];
  return targets
    .map((target, index) => ({ target, index }))
    .sort(
      (a, b) =>
        b.target.usage.active_seconds - a.target.usage.active_seconds ||
        a.index - b.index,
    )
    .map(({ target }) => target);
}
