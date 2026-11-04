import {
  fetchProcessUsage,
  fetchSiteUsage,
  isSiteTrackingBrowser,
} from "../api";
import { createPeriodView } from "../components/period/PeriodView";
import { createBucketChart } from "../components/usage/BucketChart";
import { createProcessIcon } from "../components/usage/ProcessIcon";
import {
  createSiteUsageList,
  createSiteUsageLoading,
  createSiteUsageUnavailable,
} from "../components/usage/SiteUsageList";
import { bucketsOf } from "../lib/period";
import { settleWithin } from "../lib/settle";
import styles from "./ProcessPage.module.css";

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
      // 칸별 차트 요청은 다른 어떤 것도 기다리지 않고 바로 시작한다. 사이트 목록은 덤이다: 어느
      // 프로세스에 붙일지 서버에 묻는 요청(처음 한 번만 실제로 나가고 이후는 기억된 값)과 사이트
      // 요청이 차트 요청과 나란히 진행되고, 못 불러와도(옛 hub 등) 차트는 그대로 보이며, 느려도
      // 차트는 최대 SITES_GRACE_MS만 늦춰진다. 이 promise는 거부되지 않고, 사이트 목록을 붙이지
      // 않는 프로세스면 null이다.
      const seriesPromise = fetchProcessUsage(process, buckets);
      const sitesPromise: Promise<HTMLElement | null> = isSiteTrackingBrowser(
        process,
      ).then((tracksSites) =>
        tracksSites
          ? fetchSiteUsage(process, period.start, period.end).then(
              createSiteUsageList,
              createSiteUsageUnavailable,
            )
          : null,
      );
      const chart = createBucketChart(
        period.unit,
        await seriesPromise,
        buckets,
      );
      // 그 안에 끝나면 차트와 함께 그린다(15초 갱신마다 자리가 깜빡이지 않게).
      const sites = await settleWithin(sitesPromise, SITES_GRACE_MS);
      if (sites === null) {
        return chart;
      }
      const page = document.createElement("div");
      page.append(chart);
      if (sites !== undefined) {
        page.append(sites);
        return page;
      }
      // 아직 모른다(느린 hub): 차트를 먼저 보여 주고 "불러오는 중" 자리를 두었다가, 도착하면
      // 사이트 목록으로 바꾼다. 사이트 목록을 붙이지 않는 프로세스로 밝혀지면 자리를 치운다.
      const slot = createSiteUsageLoading();
      page.append(slot);
      void sitesPromise.then((loaded) => {
        if (loaded === null) {
          slot.remove();
        } else {
          slot.replaceWith(loaded);
        }
      });
      return page;
    },
  });

  root.replaceChildren(title, view.element);
  return view.destroy;
}
