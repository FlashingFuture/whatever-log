import styles from "./UsageLegend.module.css";

function legendItem(dotClass: string, label: string): HTMLSpanElement {
  const item = document.createElement("span");

  const dot = document.createElement("span");
  dot.className = dotClass;

  item.append(dot, document.createTextNode(label));
  return item;
}

/** 막대 세 구간의 색이 무엇을 뜻하는지. 홈과 상세가 같이 쓴다. */
export function createUsageLegend(): HTMLElement {
  const legend = document.createElement("div");
  legend.className = styles.legend;
  legend.append(
    legendItem(styles.dotActive, "활성"),
    legendItem(styles.dotIdle, "유휴"),
    legendItem(styles.dotBackground, "백그라운드"),
  );
  return legend;
}
