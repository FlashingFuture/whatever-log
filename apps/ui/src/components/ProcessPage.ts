import { fetchProcessUsage, fetchSiteUsage } from "../api";
import { isBrowserProcess } from "../browsers";
import { bucketsOf } from "../period";
import { settleWithin } from "../settle";
import { createBucketChart } from "./BucketChart";
import { createPeriodView } from "./PeriodView";
import { createProcessIcon } from "./ProcessIcon";
import styles from "./ProcessPage.module.css";
import {
  createSiteUsageList,
  createSiteUsageLoading,
  createSiteUsageUnavailable,
} from "./SiteUsageList";

// 차트가 준비된 뒤 사이트 목록을 더 기다려 주는 시간. 이보다 느리면 차트를 먼저 보여 준다.
const SITES_GRACE_MS = 300;

/**
 * 프로세스 상세 화면: 아이콘 + 이름, 그 아래에 선택한 구간을 칸(일: 시간, 주/월:
 * 날짜)으로 나눈 사용 시간. 브라우저(Chrome·Edge 등)는 그 아래에 사이트별 사용 시간이 더 붙는다.
 * 구간 이동은 홈과 같은 PeriodView를 쓴다.
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
      // 사이트 목록은 덤이다: 칸별 차트와 같이 요청하되, 못 불러와도(옛 hub 등) 차트는 그대로
      // 보여 주고, 느려도 차트는 최대 SITES_GRACE_MS만 늦춰진다. 이 promise는 거부되지 않는다.
      const sitesPromise = isBrowserProcess(process)
        ? fetchSiteUsage(process, period.start, period.end).then(
            createSiteUsageList,
            createSiteUsageUnavailable,
          )
        : null;
      const chart = createBucketChart(
        period.unit,
        await fetchProcessUsage(process, buckets),
        buckets,
      );
      if (sitesPromise === null) {
        return chart;
      }
      // 그 안에 도착하면 차트와 함께 그린다(15초 갱신마다 자리가 깜빡이지 않게). 아니면 차트를
      // 그리고 "불러오는 중" 자리를 두었다가 도착하면 바꾼다.
      const sites = await settleWithin(sitesPromise, SITES_GRACE_MS);
      const slot = sites ?? createSiteUsageLoading();
      if (sites === undefined) {
        void sitesPromise.then((loaded) => slot.replaceWith(loaded));
      }
      const page = document.createElement("div");
      page.append(chart, slot);
      return page;
    },
  });

  root.replaceChildren(title, view.element);
  return view.destroy;
}
