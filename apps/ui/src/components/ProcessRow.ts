import type { ProcessUsage } from "../api";
import { createProcessIcon } from "./ProcessIcon";
import styles from "./ProcessRow.module.css";
import { createUsageRow } from "./UsageRow";

/** 홈의 프로세스 한 줄. 누르면 그 프로세스의 상세 화면으로 간다. */
export function createProcessRow(
  row: ProcessUsage,
  maxTotal: number,
): HTMLElement {
  const label = document.createElement("span");
  label.className = styles.label;
  // 9rem보다 긴 이름은 ellipsis로 잘리므로, title(마우스 호버 툴팁)로 전체
  // 이름을 확인할 수 있게 한다.
  label.title = row.process;
  const name = document.createElement("span");
  name.className = styles.name;
  // 프로세스 이름은 OS에서 온 값이라 innerHTML로 바로 꽂지 않고
  // textContent로 넣어 혹시 모를 마크업 삽입을 피한다.
  name.textContent = row.process;
  label.append(createProcessIcon(row.process), name);

  return createUsageRow({
    label,
    usage: row,
    maxTotal,
    description: row.process,
    route: { name: "process", process: row.process },
  });
}
