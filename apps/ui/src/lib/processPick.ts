/**
 * 연결 대상을 고르는 화면의 순수 로직(DOM 없음). 연결 대상은 프로세스와 브라우저의 사이트(세부 페이지)다.
 * 한 대상은 하나의 목표에만 연결되고, 브라우저 전체(프로세스)와 그 안의 사이트는 같은 시간을 두 번 세게 되므로
 * 함께 연결할 수 없다(서버가 같은 규칙으로 검증한다 — 여기서는 고를 수 있는 것만 미리 걸러 보여 준다).
 */

/** 어느 브라우저(프로세스 이름)에서 본 어느 사이트(도메인)인지. */
export interface SiteRef {
  browser: string;
  domain: string;
}

/** 이 모듈이 필요한 목표의 모양(Goal의 일부). 사이트가 없는 옛 모양도 받는다. */
export interface GoalLike {
  id: number;
  name: string;
  processes: readonly string[];
  sites?: readonly SiteRef[];
}

/** 목표에 연결(또는 해제)하는 대상 하나. */
export type LinkTarget =
  | { kind: "process"; process: string }
  | { kind: "site"; site: SiteRef };

export interface ProcessSplit {
  /** 이 목표에 연결된 프로세스. */
  linked: string[];
  /** 추적된 프로세스 중 아직 어느 목표에도 연결되지 않은 것 — 이 목표에 추가할 수 있다. */
  available: string[];
  /** 다른 목표에 이미 연결돼 있어 이 목표에는 추가할 수 없는 것(어느 목표인지 함께). */
  takenByOthers: { process: string; goalName: string }[];
  /** 브라우저 안의 사이트가 어느 목표에 연결돼 있어 브라우저 전체는 추가할 수 없는 것(어느 목표인지 함께). */
  blocked: { process: string; goalName: string }[];
  /** 이 목표에 연결된 사이트. */
  linkedSites: SiteRef[];
  /** 추적된 사이트 중 어느 목표에도 연결되지 않았고 브라우저 전체도 연결되지 않은 것 — 추가할 수 있다. */
  availableSites: SiteRef[];
  /** 다른 목표에 이미 연결돼 있는 사이트(어느 목표인지 함께). */
  takenSitesByOthers: { site: SiteRef; goalName: string }[];
}

/** 프로세스 이름의 비교 키. Windows 파일 이름은 대소문자를 구분하지 않아 같은 프로세스로 본다. */
export function processKey(name: string): string {
  // 서버(Python casefold)와 맞춘다: toLowerCase만으로는 "ß"가 "ss"와 같은 키가 되지 않는다. 대문자로 올렸다가
  // 내리면 casefold와 같은 결과가 된다("Straße" → "strasse").
  return name.toUpperCase().toLowerCase();
}

/** 사이트의 비교 키(서버의 site_key와 같다): 브라우저 키 + "/" + 도메인. */
export function siteKey(site: SiteRef): string {
  return `${processKey(site.browser)}/${site.domain.toLowerCase()}`;
}

/** 대상 하나의 비교 키(프로세스와 사이트가 섞이지 않게 종류를 앞에 붙인다). */
export function targetKey(target: LinkTarget): string {
  return target.kind === "process"
    ? `process:${processKey(target.process)}`
    : `site:${siteKey(target.site)}`;
}

function byKey(a: string, b: string): number {
  return processKey(a).localeCompare(processKey(b), "en");
}

function bySite(a: SiteRef, b: SiteRef): number {
  return siteKey(a).localeCompare(siteKey(b), "en");
}

/**
 * 연결 화면의 목록들을 나눈다. tracked는 추적된 프로세스 이름들, goals는 모든 목표, goalId는 지금 보는
 * 목표, trackedSites는 추적된 사이트들이다. 각 목록은 이름(대소문자 무시) 순이다.
 */
export function splitProcesses(
  tracked: readonly string[],
  goals: readonly GoalLike[],
  goalId: number,
  trackedSites: readonly SiteRef[] = [],
): ProcessSplit {
  const current = goals.find((goal) => goal.id === goalId);
  const linked = [...(current?.processes ?? [])].sort(byKey);
  const linkedKeys = new Set(linked.map(processKey));
  const linkedSites = [...(current?.sites ?? [])].sort(bySite);
  const linkedSiteKeys = new Set(linkedSites.map(siteKey));

  const owner = new Map<string, string>();
  const siteOwner = new Map<string, string>();
  // 어느 브라우저(키)의 사이트가 어느 목표(이 목표 포함)에 연결돼 있는지.
  const browserSiteGoal = new Map<string, string>();
  for (const goal of goals) {
    for (const site of goal.sites ?? []) {
      if (goal.id !== goalId) {
        siteOwner.set(siteKey(site), goal.name);
      }
      browserSiteGoal.set(processKey(site.browser), goal.name);
    }
    if (goal.id !== goalId) {
      for (const process of goal.processes) {
        owner.set(processKey(process), goal.name);
      }
    }
  }
  // 브라우저 전체가 어느 목표(이 목표 포함)에 연결돼 있으면 그 안의 사이트는 따로 연결할 수 없다.
  const wholeBrowsers = new Set(linkedKeys);
  for (const key of owner.keys()) {
    wholeBrowsers.add(key);
  }

  // 대소문자만 다른 이름이 따로 기록돼 있어도(같은 프로세스) 한 번만 보여 준다.
  const seen = new Set<string>();
  const addable = tracked.filter((process) => {
    const key = processKey(process);
    if (linkedKeys.has(key) || owner.has(key) || seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
  const available = addable
    .filter((process) => !browserSiteGoal.has(processKey(process)))
    .sort(byKey);
  const blocked = addable
    .filter((process) => browserSiteGoal.has(processKey(process)))
    .map((process) => ({
      process,
      goalName: browserSiteGoal.get(processKey(process)) ?? "",
    }))
    .sort((a, b) => byKey(a.process, b.process));

  const takenByOthers = goals
    .filter((goal) => goal.id !== goalId)
    .flatMap((goal) =>
      goal.processes.map((process) => ({ process, goalName: goal.name })),
    )
    .sort((a, b) => byKey(a.process, b.process));

  const availableSites = trackedSites
    .filter(
      (site) =>
        !linkedSiteKeys.has(siteKey(site)) &&
        !siteOwner.has(siteKey(site)) &&
        !wholeBrowsers.has(processKey(site.browser)),
    )
    .sort(bySite);

  const takenSitesByOthers = goals
    .filter((goal) => goal.id !== goalId)
    .flatMap((goal) =>
      (goal.sites ?? []).map((site) => ({ site, goalName: goal.name })),
    )
    .sort((a, b) => bySite(a.site, b.site));

  return {
    linked,
    available,
    takenByOthers,
    blocked,
    linkedSites,
    availableSites,
    takenSitesByOthers,
  };
}

/** 목록에 프로세스를 더한 새 목록(이미 있으면 그대로). 이름 순으로 돌려준다. */
export function addProcess(list: readonly string[], name: string): string[] {
  if (list.some((item) => processKey(item) === processKey(name))) {
    return [...list].sort(byKey);
  }
  return [...list, name].sort(byKey);
}

/** 목록에서 프로세스를 뺀 새 목록. */
export function removeProcess(list: readonly string[], name: string): string[] {
  return list.filter((item) => processKey(item) !== processKey(name));
}

/** 목록에 사이트를 더한 새 목록(이미 있으면 그대로). */
export function addSite(list: readonly SiteRef[], site: SiteRef): SiteRef[] {
  if (list.some((item) => siteKey(item) === siteKey(site))) {
    return [...list].sort(bySite);
  }
  return [...list, site].sort(bySite);
}

/** 목록에서 사이트를 뺀 새 목록. */
export function removeSite(list: readonly SiteRef[], site: SiteRef): SiteRef[] {
  return list.filter((item) => siteKey(item) !== siteKey(site));
}

/** 끌어다 놓을 때 주고받는 글자(JSON)로 만든다. */
export function encodeTarget(target: LinkTarget): string {
  return JSON.stringify(target);
}

/** encodeTarget의 반대. 모양이 맞지 않으면 null(다른 곳에서 끌어온 글자 등). */
export function decodeTarget(text: string): LinkTarget | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (record.kind === "process" && typeof record.process === "string") {
    return { kind: "process", process: record.process };
  }
  const site = record.site as Record<string, unknown> | undefined;
  if (
    record.kind === "site" &&
    typeof site === "object" &&
    site !== null &&
    typeof site.browser === "string" &&
    typeof site.domain === "string"
  ) {
    return {
      kind: "site",
      site: { browser: site.browser, domain: site.domain },
    };
  }
  return null;
}
