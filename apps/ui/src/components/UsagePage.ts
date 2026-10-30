import { fetchUsage } from "../api";
import {
  anchorForUnitChange,
  CURRENT_PERIOD_HINT,
  formatPeriod,
  isCurrentPeriod,
  type Period,
  type PeriodUnit,
  periodContaining,
  shiftPeriod,
} from "../period";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";
import { createCalendarPicker } from "./CalendarPicker";
import { createErrorView } from "./ErrorView";
import { createPeriodListPicker } from "./PeriodListPicker";
import { closePopover, isPopoverOpen, togglePopover } from "./Popover";
import { createSegmentedControl } from "./SegmentedControl";
import { createStepper } from "./Stepper";
import { createUsageChart } from "./UsageChart";

injectStyle(
  "usage-page",
  `
  .usage-page-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin-bottom: 1.25rem;
  }
  .usage-page-loading {
    color: ${theme.colors.textMuted};
  }
`,
);

// recorder의 기본 샘플링 간격(15초, apps/recorder/__main__.py의
// DEFAULT_INTERVAL_SECONDS)과 맞춰서, 현재 구간을 보고 있으면 "실시간으로
// 쌓이는" 느낌이 나게 주기적으로 다시 불러온다. 지난 구간은 더 바뀌지 않으니
// 다시 불러오지 않는다.
const REFRESH_INTERVAL_MS = 15_000;

const UNIT_OPTIONS: { value: PeriodUnit; label: string }[] = [
  { value: "day", label: "일" },
  { value: "week", label: "주" },
  { value: "month", label: "월" },
];

/** "사용 현황" 화면 전체: 단위 선택 + 구간 이동 + 차트. 상태(보고 있는 구간)를 직접 갖는다. */
export function mountUsagePage(root: Element): void {
  let period = periodContaining("day", new Date());
  // 구간을 빠르게 넘기면 이전 요청의 응답이 나중에 도착할 수 있다 — 가장
  // 최근에 보낸 요청의 응답만 그린다.
  let latestRequestId = 0;

  const title = document.createElement("h1");
  title.textContent = "사용 현황";
  const header = document.createElement("div");
  header.className = "usage-page-header";
  const content = document.createElement("div");
  root.replaceChildren(title, header, content);

  function goTo(next: Period): void {
    period = next;
    renderHeader();
    load();
  }

  function goPrev(): void {
    goTo(shiftPeriod(period, -1));
  }

  function goNext(): void {
    if (!isCurrentPeriod(period, new Date())) {
      goTo(shiftPeriod(period, 1));
    }
  }

  /** 팝업에서 고른 구간으로 이동하고, 다시 그려진 라벨 버튼으로 포커스를 돌린다. */
  function selectFromPicker(next: Period): void {
    closePopover();
    goTo(next);
    header.querySelector<HTMLElement>('[aria-haspopup="dialog"]')?.focus();
  }

  function openPicker(anchor: HTMLButtonElement): void {
    const now = new Date();
    const picker =
      period.unit === "day"
        ? createCalendarPicker({
            selected: period,
            now,
            onSelect: selectFromPicker,
          })
        : createPeriodListPicker({
            unit: period.unit,
            selected: period,
            now,
            onSelect: selectFromPicker,
          });
    togglePopover(anchor, picker, "구간 선택");
  }

  // 마지막으로 그린 헤더가 "현재 구간" 상태였는지 — 주기 갱신 때 바뀐 경우에만
  // 헤더를 다시 그린다(열려 있는 팝업의 기준 버튼이 갈아치워지지 않게).
  let headerShowsCurrent = false;

  function renderHeader(): void {
    const isCurrent = isCurrentPeriod(period, new Date());
    headerShowsCurrent = isCurrent;
    header.replaceChildren(
      createSegmentedControl({
        options: UNIT_OPTIONS,
        selected: period.unit,
        ariaLabel: "조회 단위",
        onChange: (unit) =>
          goTo(periodContaining(unit, anchorForUnitChange(period, new Date()))),
      }),
      createStepper({
        label: formatPeriod(period),
        hint: isCurrent ? CURRENT_PERIOD_HINT[period.unit] : undefined,
        canGoPrev: true,
        canGoNext: !isCurrent,
        onPrev: goPrev,
        onNext: goNext,
        onLabelClick: openPicker,
      }),
    );
  }

  function load({ isBackgroundRefresh = false } = {}): void {
    const requestId = ++latestRequestId;
    if (!isBackgroundRefresh) {
      const loading = document.createElement("p");
      loading.className = "usage-page-loading";
      loading.textContent = "불러오는 중…";
      content.replaceChildren(loading);
    }

    fetchUsage(period.start, period.end)
      .then((usage) => {
        if (requestId === latestRequestId) {
          content.replaceChildren(createUsageChart(usage));
        }
      })
      .catch((error: unknown) => {
        // 주기적 갱신이 일시적으로 실패한 거라면(hub가 잠깐 재시작하는 중 등),
        // 이미 잘 보여주고 있던 화면을 에러 화면으로 덮어쓰지 않는다 — 다음
        // 주기에 다시 시도된다.
        if (requestId === latestRequestId && !isBackgroundRefresh) {
          content.replaceChildren(createErrorView(String(error), () => load()));
        }
      });
  }

  document.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      return;
    }
    // 팝업(달력·목록)은 방향키를 자기 안에서 쓴다 — 뒤의 구간이 같이 넘어가면 안 된다.
    if (isPopoverOpen() || event.defaultPrevented) {
      return;
    }
    if (event.key === "ArrowLeft") {
      goPrev();
    } else if (event.key === "ArrowRight") {
      goNext();
    }
  });

  setInterval(() => {
    const isCurrent = isCurrentPeriod(period, new Date());
    // 자정(혹은 월요일·1일)을 넘기면 보고 있던 구간이 더 이상 "현재"가 아니게
    // 된다 — 헤더를 다시 그려서 → 버튼을 켜고 "오늘" 표시를 뗀다. 열려 있던
    // 팝업은 미래/현재 표시가 틀려지므로 닫는다.
    if (isCurrent !== headerShowsCurrent) {
      closePopover();
      renderHeader();
    }
    if (isCurrent) {
      load({ isBackgroundRefresh: true });
    }
  }, REFRESH_INTERVAL_MS);

  renderHeader();
  load();
}
