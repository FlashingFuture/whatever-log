import type { ProcessUsage } from "../api";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";

injectStyle(
  "bar-row",
  `
  .bar-row {
    display: grid;
    grid-template-columns: 9rem 1fr 7rem;
    align-items: center;
    gap: 0.75rem;
  }
  .bar-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: ${theme.colors.text};
  }
  .bar-track {
    height: 1rem;
    background: ${theme.colors.track};
    border-radius: 4px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    display: flex;
  }
  .bar-value {
    font-size: 0.85rem;
    color: ${theme.colors.textMuted};
    text-align: right;
  }
`,
);

function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours === 0 ? `${minutes}분` : `${hours}시간 ${minutes}분`;
}

function segment(widthPct: number, color: string): HTMLDivElement {
  const div = document.createElement("div");
  div.style.width = `${widthPct}%`;
  div.style.height = "100%";
  div.style.background = color;
  return div;
}

export function createBarRow(row: ProcessUsage, maxTotal: number): HTMLElement {
  const item = document.createElement("div");
  item.className = "bar-row";

  const label = document.createElement("span");
  label.className = "bar-label";
  // 프로세스 이름은 OS에서 온 값이라 innerHTML로 바로 꽂지 않고
  // textContent로 넣어 혹시 모를 마크업 삽입을 피한다.
  label.textContent = row.process;

  const track = document.createElement("div");
  track.className = "bar-track";

  const fill = document.createElement("div");
  fill.className = "bar-fill";
  fill.style.width =
    maxTotal > 0 ? `${(row.total_seconds / maxTotal) * 100}%` : "0%";

  // bar-fill의 폭 자체가 이 프로세스의 total_seconds를 나타내고, 그 안을
  // active/idle/background 세 구간으로 나란히 채운다 — 세 값은 겹치지
  // 않고 합이 total_seconds와 같다(packages/aggregation/range.py).
  if (row.total_seconds > 0) {
    fill.append(
      segment(
        (row.active_seconds / row.total_seconds) * 100,
        theme.colors.active,
      ),
      segment((row.idle_seconds / row.total_seconds) * 100, theme.colors.idle),
      segment(
        (row.background_seconds / row.total_seconds) * 100,
        theme.colors.backgroundSegment,
      ),
    );
  }
  track.append(fill);

  const value = document.createElement("span");
  value.className = "bar-value";
  value.textContent = `${formatDuration(row.active_seconds)} / ${formatDuration(row.total_seconds)}`;

  item.append(label, track, value);
  return item;
}
