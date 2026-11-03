import type { SiteRangeUsage } from "../api";
import { maxOf } from "../stats";
import { createSiteIcon } from "./ProcessIcon";
import styles from "./SiteUsageList.module.css";
import { createUsageRow } from "./UsageRow";

function heading(): HTMLElement {
  const title = document.createElement("h2");
  title.className = styles.title;
  title.textContent = "사이트별";
  return title;
}

function note(text: string): HTMLElement {
  const element = document.createElement("p");
  element.className = styles.note;
  element.textContent = text;
  return element;
}

/**
 * 브라우저 상세 화면의 사이트(도메인)별 사용 시간. 프로세스 목록과 같은 줄 모양을 쓰되, 사이트는
 * foreground일 때만 알 수 있어 백그라운드 구간은 없다. 사이트는 브라우저 창 제목으로 추정한
 * 값이라 일부 시간은 어느 사이트에도 들어가지 않는다 — 그 점을 화면에 밝힌다.
 */
export function createSiteUsageList(usage: SiteRangeUsage): HTMLElement {
  const section = document.createElement("section");
  section.className = styles.section;
  section.append(heading());

  if (usage.by_site.length === 0) {
    section.append(note("이 구간에는 기록된 사이트가 없습니다."));
    return section;
  }

  // 가장 오래 본 사이트를 기준으로 막대 폭을 정한다(다른 목록과 같은 방식).
  const maxTotal = maxOf(usage.by_site, (site) => site.total_seconds);
  const list = document.createElement("div");
  list.className = styles.list;
  for (const site of usage.by_site) {
    const label = document.createElement("span");
    label.className = styles.label;
    label.title = site.domain; // 긴 도메인은 잘리니 전체를 툴팁으로 보여 준다
    const name = document.createElement("span");
    name.className = styles.name;
    // 도메인은 방문한 사이트에서 온 값이라 textContent로만 넣는다.
    name.textContent = site.domain;
    label.append(createSiteIcon(site.domain), name);
    list.append(
      createUsageRow({
        label,
        usage: { ...site, background_seconds: 0 },
        maxTotal,
        description: site.domain,
      }),
    );
  }

  section.append(
    list,
    note("창 제목으로 추정한 값이라, 알아내지 못한 시간은 포함되지 않습니다."),
  );
  return section;
}

/** 사이트 정보를 아직 받는 중일 때의 자리. 칸별 차트를 먼저 보여 주고, 도착하면 이 자리를 바꾼다. */
export function createSiteUsageLoading(): HTMLElement {
  const section = document.createElement("section");
  section.className = styles.section;
  section.append(heading(), note("불러오는 중…"));
  return section;
}

/** 사이트 정보를 불러오지 못했을 때(옛 hub 등) 상세 화면 전체를 막지 않고 알리는 자리. */
export function createSiteUsageUnavailable(): HTMLElement {
  const section = document.createElement("section");
  section.className = styles.section;
  section.append(heading(), note("사이트 정보를 불러오지 못했습니다."));
  return section;
}
