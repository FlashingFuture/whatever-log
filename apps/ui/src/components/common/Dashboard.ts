import styles from "./Dashboard.module.css";

/**
 * 왼쪽 요약 + 오른쪽 내용(차트)의 두 칸 틀. 홈과 프로세스 상세가 같이 쓴다. 좁은 창에서는 요약이 위, 내용이 아래로 쌓이고,
 * 넓은 창에서 내용이 길어져 페이지가 스크롤돼도 요약은 화면 위쪽에 남는다.
 */
export function createDashboard(side: Node[], main: Node[]): HTMLElement {
  const dashboard = document.createElement("div");
  dashboard.className = styles.dashboard;
  const sideColumn = document.createElement("div");
  sideColumn.className = styles.side;
  sideColumn.append(...side);
  const mainColumn = document.createElement("div");
  mainColumn.className = styles.main;
  mainColumn.append(...main);
  dashboard.append(sideColumn, mainColumn);
  return dashboard;
}
