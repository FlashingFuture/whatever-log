import { fetchProcessUsage } from "../api";
import { bucketsOf } from "../period";
import { injectStyle } from "../styles/injectStyle";
import { createBucketChart } from "./BucketChart";
import { createPeriodView } from "./PeriodView";
import { createProcessIcon } from "./ProcessIcon";

injectStyle(
  "process-page",
  `
  .process-page-title {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin: 0 0 1.25rem;
    font-size: 1.5rem;
  }
  .process-page-name {
    overflow-wrap: anywhere;
  }
`,
);

/**
 * 프로세스 상세 화면: 아이콘 + 이름, 그 아래에 선택한 구간을 칸(일: 시간, 주/월:
 * 날짜)으로 나눈 사용 시간. 구간 이동은 홈과 같은 PeriodView를 쓴다.
 */
export function mountProcessPage(
  root: HTMLElement,
  process: string,
): () => void {
  const title = document.createElement("h1");
  title.className = "process-page-title";
  const name = document.createElement("span");
  name.className = "process-page-name";
  name.textContent = process;
  title.append(createProcessIcon(process, { large: true }), name);

  const view = createPeriodView({
    loadContent: async (period) =>
      createBucketChart(
        period.unit,
        await fetchProcessUsage(process, bucketsOf(period)),
      ),
  });

  root.replaceChildren(title, view.element);
  return view.destroy;
}
