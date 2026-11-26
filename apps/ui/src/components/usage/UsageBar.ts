import styles from "./UsageBar.module.css";
import type { UsageNumbers } from "./UsageRow";

function segment(heightPct: number, className: string): HTMLDivElement {
  const div = document.createElement("div");
  div.className = className;
  div.style.height = `${heightPct}%`;
  return div;
}

/**
 * 세로 막대 하나: 높이 = 전체 시간(가장 큰 칸 기준), 안쪽은 아래서부터 활성/유휴/백그라운드가 쌓인다.
 * 홈의 프로세스 칸과 프로세스 상세의 시간 칸이 같이 쓴다 — 칸의 이름·라벨은 쓰는 쪽이 붙인다.
 * 막대는 색으로만 구분되므로 수치는 쓰는 쪽이 글자(aria-label·title)로도 줘야 한다.
 */
export function createUsageBar(
  usage: UsageNumbers,
  maxTotal: number,
): HTMLDivElement {
  const track = document.createElement("div");
  track.className = styles.track;
  const fill = document.createElement("div");
  fill.className = styles.fill;
  fill.style.height =
    maxTotal > 0 ? `${(usage.total_seconds / maxTotal) * 100}%` : "0%";
  if (usage.total_seconds > 0) {
    const pct = (seconds: number): number =>
      (seconds / usage.total_seconds) * 100;
    // 위에서 아래로: 백그라운드, 유휴, 활성 — 활성이 바닥에 놓여 칸마다 나란히 비교된다.
    fill.append(
      segment(pct(usage.background_seconds), styles.segBackground),
      segment(pct(usage.idle_seconds), styles.segIdle),
      segment(pct(usage.active_seconds), styles.segActive),
    );
  }
  track.append(fill);
  return track;
}
