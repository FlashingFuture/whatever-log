import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";

injectStyle(
  "usage-legend",
  `
  .usage-legend {
    display: flex;
    gap: 1rem;
    font-size: 0.8rem;
    color: ${theme.colors.textMuted};
    margin-bottom: 0.4rem;
  }
  .usage-legend-dot {
    display: inline-block;
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    margin-right: 0.3rem;
  }
`,
);

function legendItem(color: string, label: string): HTMLSpanElement {
  const item = document.createElement("span");

  const dot = document.createElement("span");
  dot.className = "usage-legend-dot";
  dot.style.background = color;

  item.append(dot, document.createTextNode(label));
  return item;
}

/** 막대 세 구간의 색이 무엇을 뜻하는지. 홈과 상세가 같이 쓴다. */
export function createUsageLegend(): HTMLElement {
  const legend = document.createElement("div");
  legend.className = "usage-legend";
  legend.append(
    legendItem(theme.colors.active, "활성"),
    legendItem(theme.colors.idle, "유휴"),
    legendItem(theme.colors.backgroundSegment, "백그라운드"),
  );
  return legend;
}
