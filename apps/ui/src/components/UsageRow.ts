import { createRouteLink, type Route } from "../router";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";

injectStyle(
  "usage-row",
  `
  .usage-row {
    display: grid;
    grid-template-columns: 9rem 1fr 10rem;
    align-items: center;
    gap: 0.75rem;
    color: inherit;
    text-decoration: none;
  }
  /* 누를 수 있는 줄(링크)만 반응한다. 옆 줄과 겹치지 않게 살짝 안쪽 여백을 둔다. */
  a.usage-row {
    margin: 0 -0.5rem;
    padding: 0.15rem 0.5rem;
    border-radius: 6px;
  }
  a.usage-row:hover {
    background: ${theme.colors.track};
  }
  a.usage-row:focus-visible {
    outline: 2px solid ${theme.colors.active};
    outline-offset: -2px;
  }
  .usage-row-track {
    height: 1rem;
    background: ${theme.colors.track};
    border-radius: 4px;
    overflow: hidden;
  }
  a.usage-row:hover .usage-row-track {
    background: ${theme.colors.background};
  }
  .usage-row-fill {
    height: 100%;
    display: flex;
  }
  .usage-row-value {
    font-size: 0.85rem;
    color: ${theme.colors.textMuted};
    text-align: right;
  }
  /* 칸이 좁으면 "활성 / 총" 사이에서만 줄을 바꾸고, "12시간 12분" 안에서는 안 끊는다. */
  .usage-row-value-part {
    white-space: nowrap;
  }
`,
);

/** 활성/유휴/백그라운드 세 구간(서로 겹치지 않고 합이 total). */
export interface UsageNumbers {
  active_seconds: number;
  idle_seconds: number;
  background_seconds: number;
  total_seconds: number;
}

export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours === 0 ? `${minutes}분` : `${hours}시간 ${minutes}분`;
}

function valuePart(text: string): HTMLSpanElement {
  const part = document.createElement("span");
  part.className = "usage-row-value-part";
  part.textContent = text;
  return part;
}

function segment(widthPct: number, color: string): HTMLDivElement {
  const div = document.createElement("div");
  div.style.width = `${widthPct}%`;
  div.style.height = "100%";
  div.style.background = color;
  return div;
}

export interface UsageRowProps {
  /** 왼쪽 칸에 들어갈 내용(프로세스 이름, 날짜 등). 무엇인지는 이 컴포넌트가 모른다. */
  label: Node;
  usage: UsageNumbers;
  /** 막대 폭의 기준(보이는 줄들 중 가장 큰 total). */
  maxTotal: number;
  /** 막대를 읽을 수 없는 사용자용 설명(스크린 리더·툴팁). 줄의 이름을 앞에 붙인다. */
  description: string;
  /** 주면 줄 전체가 그곳으로 가는 링크가 된다. */
  route?: Route;
}

/**
 * "라벨 | 3색 막대 | 활성 / 총" 한 줄. 프로세스 목록(홈)과 칸별 목록(상세)이
 * 같이 쓴다 — 줄이 무엇을 나타내는지는 라벨과 설명으로만 받는다.
 */
export function createUsageRow(props: UsageRowProps): HTMLElement {
  const { usage } = props;
  const row = props.route
    ? createRouteLink(props.route)
    : document.createElement("div");
  row.classList.add("usage-row");

  const breakdown =
    `${props.description}: 활성 ${formatDuration(usage.active_seconds)}, ` +
    `유휴 ${formatDuration(usage.idle_seconds)}, ` +
    `백그라운드 ${formatDuration(usage.background_seconds)}, ` +
    `총 ${formatDuration(usage.total_seconds)}`;

  const track = document.createElement("div");
  track.className = "usage-row-track";
  // 막대의 세 구간은 색으로만 구분되어 있어서, 스크린 리더 사용자나 색을 구분하기
  // 어려운 사용자는 값을 알 수 없다 — role="img" + aria-label로 전체 수치를
  // 텍스트로도 제공한다. title을 같이 줘서 마우스 호버로도 같은 내용을 볼 수 있다.
  track.setAttribute("role", "img");
  track.setAttribute("aria-label", breakdown);
  track.title = breakdown;

  const fill = document.createElement("div");
  fill.className = "usage-row-fill";
  fill.style.width =
    props.maxTotal > 0
      ? `${(usage.total_seconds / props.maxTotal) * 100}%`
      : "0%";

  // fill의 폭 자체가 total_seconds를 나타내고, 그 안을 세 구간으로 나란히 채운다.
  if (usage.total_seconds > 0) {
    fill.append(
      segment(
        (usage.active_seconds / usage.total_seconds) * 100,
        theme.colors.active,
      ),
      segment(
        (usage.idle_seconds / usage.total_seconds) * 100,
        theme.colors.idle,
      ),
      segment(
        (usage.background_seconds / usage.total_seconds) * 100,
        theme.colors.backgroundSegment,
      ),
    );
  }
  track.append(fill);

  const value = document.createElement("span");
  value.className = "usage-row-value";
  value.append(
    valuePart(formatDuration(usage.active_seconds)),
    " / ",
    valuePart(formatDuration(usage.total_seconds)),
  );

  row.append(props.label, track, value);
  return row;
}
