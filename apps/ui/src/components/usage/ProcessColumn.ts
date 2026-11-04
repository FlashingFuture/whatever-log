import type { ProcessUsage } from "../../api";
import { formatDuration, truncateName } from "../../lib/format";
import { createRouteLink } from "../../router/router";
import styles from "./ProcessColumn.module.css";
import { createProcessIcon } from "./ProcessIcon";

// 열이 좁아서 긴 이름은 이 글자 수에서 "…"로 줄인다(전체 이름은 title/aria-label로).
const NAME_MAX_CHARS = 10;

function segment(heightPct: number, className: string): HTMLDivElement {
  const div = document.createElement("div");
  div.className = className;
  div.style.height = `${heightPct}%`;
  return div;
}

/**
 * 홈 차트의 프로세스 한 칸: 세로 막대(높이 = 전체 시간, 안쪽은 활성/유휴/백그라운드가
 * 아래서부터 쌓임) + 아이콘 + 이름 + 활성/전체 시간. 누르면 그 프로세스의 상세로 간다.
 */
export function createProcessColumn(
  row: ProcessUsage,
  maxTotal: number,
): HTMLElement {
  const link = createRouteLink({ name: "process", process: row.process });
  link.className = styles.column;

  const breakdown =
    `${row.process}: 활성 ${formatDuration(row.active_seconds)}, ` +
    `유휴 ${formatDuration(row.idle_seconds)}, ` +
    `백그라운드 ${formatDuration(row.background_seconds)}, ` +
    `총 ${formatDuration(row.total_seconds)}`;
  // 막대는 색으로만 구분되므로 수치를 텍스트로도 준다(링크의 이름이 된다).
  link.setAttribute("aria-label", breakdown);
  link.title = breakdown;

  const track = document.createElement("div");
  track.className = styles.track;
  const fill = document.createElement("div");
  fill.className = styles.fill;
  fill.style.height =
    maxTotal > 0 ? `${(row.total_seconds / maxTotal) * 100}%` : "0%";
  if (row.total_seconds > 0) {
    const pct = (seconds: number): number =>
      (seconds / row.total_seconds) * 100;
    // 위에서 아래로: 백그라운드, 유휴, 활성 — 활성이 바닥에 놓여 칸마다 나란히 비교된다.
    fill.append(
      segment(pct(row.background_seconds), styles.segBackground),
      segment(pct(row.idle_seconds), styles.segIdle),
      segment(pct(row.active_seconds), styles.segActive),
    );
  }
  track.append(fill);

  const name = document.createElement("span");
  name.className = styles.name;
  // 프로세스 이름은 OS에서 온 값이라 textContent로만 넣는다.
  name.textContent = truncateName(row.process, NAME_MAX_CHARS);

  const active = document.createElement("span");
  active.className = styles.active;
  active.textContent = formatDuration(row.active_seconds);
  const total = document.createElement("span");
  total.className = styles.total;
  total.textContent = `총 ${formatDuration(row.total_seconds)}`;

  link.append(track, createProcessIcon(row.process), name, active, total);
  return link;
}
