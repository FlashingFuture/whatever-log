import { fetchProcessUsage } from "../api";
import { bucketsOf } from "../period";
import { createBucketChart } from "./BucketChart";
import { createPeriodView } from "./PeriodView";
import { createProcessIcon } from "./ProcessIcon";
import styles from "./ProcessPage.module.css";

/**
 * 프로세스 상세 화면: 아이콘 + 이름, 그 아래에 선택한 구간을 칸(일: 시간, 주/월:
 * 날짜)으로 나눈 사용 시간. 구간 이동은 홈과 같은 PeriodView를 쓴다.
 */
export function mountProcessPage(
  root: HTMLElement,
  process: string,
): () => void {
  const title = document.createElement("h1");
  title.className = styles.title;
  const name = document.createElement("span");
  name.className = styles.name;
  name.textContent = process;
  title.append(createProcessIcon(process, { large: true }), name);

  const view = createPeriodView({
    loadContent: async (period) => {
      // 라벨은 클라이언트가 계산한 칸으로 만든다(서버 응답의 시각이 아니라) — 같은
      // 시(時)가 두 번 나오는 일광절약시간 종료일의 표시가 칸에 들어 있다.
      const buckets = bucketsOf(period);
      return createBucketChart(
        period.unit,
        await fetchProcessUsage(process, buckets),
        buckets,
      );
    },
  });

  root.replaceChildren(title, view.element);
  return view.destroy;
}
