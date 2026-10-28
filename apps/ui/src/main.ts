import "./style.css";

// apps/hub가 고정 포트로 뜬다(apps/desktop이 자식 프로세스로 띄움).
const HUB_URL = "http://127.0.0.1:8787";

// recorder의 기본 샘플링 간격(15초, apps/recorder/__main__.py의
// DEFAULT_INTERVAL_SECONDS)과 맞춰서, 화면이 "실시간으로 쌓이는" 느낌이
// 나게 주기적으로 다시 불러온다.
const REFRESH_INTERVAL_MS = 15_000;

interface ProcessUsage {
  process: string;
  active_seconds: number;
  total_seconds: number;
}

interface RangeUsage {
  start: string;
  end: string;
  by_process: ProcessUsage[];
}

function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) {
    return `${minutes}분`;
  }
  return `${hours}시간 ${minutes}분`;
}

function renderUsage(app: Element, usage: RangeUsage): void {
  app.innerHTML = "<h1>최근 24시간 사용 현황</h1>";

  if (usage.by_process.length === 0) {
    const empty = document.createElement("p");
    empty.textContent = "기록된 사용 내역이 없습니다.";
    app.append(empty);
    return;
  }

  // 가장 오래 떠 있던(total) 프로세스를 기준으로 막대 폭을 정한다 — 범위
  // 전체 길이(24시간)를 기준으로 하면 거의 모든 막대가 짤막해져서 비교가
  // 어렵다.
  const maxTotal = Math.max(
    ...usage.by_process.map((row) => row.total_seconds),
  );

  const chart = document.createElement("div");
  chart.className = "bar-chart";

  for (const row of usage.by_process) {
    const totalPct = maxTotal > 0 ? (row.total_seconds / maxTotal) * 100 : 0;
    const activePct =
      row.total_seconds > 0
        ? (row.active_seconds / row.total_seconds) * 100
        : 0;

    const item = document.createElement("div");
    item.className = "bar-row";

    const label = document.createElement("span");
    label.className = "bar-label";
    // 프로세스 이름은 OS에서 온 값이라 innerHTML로 바로 꽂지 않고
    // textContent로 넣어 혹시 모를 마크업 삽입을 피한다.
    label.textContent = row.process;

    const track = document.createElement("div");
    track.className = "bar-track";

    // 연한 색 막대(total, background 포함)의 폭을 totalPct로 잡고, 그 안에
    // 진한 색 막대(active, foreground에서 idle 아니었던 시간)를 중첩시켜서
    // 하나의 두 색 막대처럼 보이게 한다.
    const totalBar = document.createElement("div");
    totalBar.className = "bar-total";
    totalBar.style.width = `${totalPct}%`;

    const activeBar = document.createElement("div");
    activeBar.className = "bar-active";
    activeBar.style.width = `${activePct}%`;
    totalBar.append(activeBar);
    track.append(totalBar);

    const value = document.createElement("span");
    value.className = "bar-value";
    value.textContent = `${formatDuration(row.active_seconds)} / ${formatDuration(row.total_seconds)}`;

    item.append(label, track, value);
    chart.append(item);
  }

  app.append(chart);
}

function renderError(app: Element, message: string): void {
  app.innerHTML = "<h1>최근 24시간 사용 현황</h1>";
  const error = document.createElement("p");
  error.textContent = `불러오지 못했습니다: ${message}`;

  // hub가 콜드 스타트로 늦게 뜨면 desktop은 이 화면을 보여준 채로 창을 연다
  // (apps/desktop/__main__.py의 _wait_for_hub_port 타임아웃 처리). hub는
  // 백그라운드에서 계속 재시도되니, 다시 열지 않고도 재시도할 방법이 있어야
  // 한다.
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "다시 시도";
  retry.addEventListener("click", () => loadUsage(app));

  app.append(error, retry);
}

function loadUsage(app: Element, { isBackgroundRefresh = false } = {}): void {
  fetch(`${HUB_URL}/api/usage?range=24h`)
    .then((response) => {
      // fetch()는 HTTP 상태와 무관하게 resolve된다 — hub가 DB를 못 읽어
      // 503을 주면 { "error": ... } 모양이라, 체크 없이 바로 RangeUsage로
      // 취급하면 renderUsage가 undefined 필드에서 깨진다.
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json() as Promise<RangeUsage>;
    })
    .then((usage) => renderUsage(app, usage))
    .catch((error: unknown) => {
      // 주기적 갱신이 일시적으로 실패한 거라면(hub가 잠깐 재시작하는 중 등),
      // 이미 잘 보여주고 있던 화면을 에러 화면으로 덮어쓰지 않는다 — 다음
      // 주기에 다시 시도된다. 최초 로드 실패나 "다시 시도" 클릭 때만 에러를
      // 보여준다.
      if (!isBackgroundRefresh) {
        renderError(app, String(error));
      }
    });
}

const app = document.querySelector("#app");
if (app) {
  loadUsage(app);
  setInterval(
    () => loadUsage(app, { isBackgroundRefresh: true }),
    REFRESH_INTERVAL_MS,
  );
}
