import "./style.css";

// apps/hub가 고정 포트로 뜬다(apps/desktop이 자식 프로세스로 띄움).
const HUB_URL = "http://127.0.0.1:8787";

interface ProcessUsage {
  process: string;
  seconds: number;
}

interface TodayUsage {
  date: string;
  total_seconds: number;
  by_process: ProcessUsage[];
}

function formatMinutes(seconds: number): string {
  return `${(seconds / 60).toFixed(1)}분`;
}

function renderUsage(app: Element, usage: TodayUsage): void {
  app.innerHTML = `
    <h1>오늘 사용 현황</h1>
    <p>${usage.date} · 총 ${formatMinutes(usage.total_seconds)}</p>
  `;

  const list = document.createElement("ul");
  if (usage.by_process.length === 0) {
    const empty = document.createElement("li");
    empty.textContent = "기록된 사용 내역이 없습니다.";
    list.append(empty);
  } else {
    for (const row of usage.by_process) {
      const item = document.createElement("li");
      // 프로세스 이름은 OS에서 온 값이라 innerHTML로 바로 꽂지 않고
      // textContent로 넣어 혹시 모를 마크업 삽입을 피한다.
      item.textContent = `${row.process} — ${formatMinutes(row.seconds)}`;
      list.append(item);
    }
  }
  app.append(list);
}

function renderError(app: Element, message: string): void {
  app.innerHTML = "<h1>오늘 사용 현황</h1>";
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

function loadUsage(app: Element): void {
  fetch(`${HUB_URL}/api/today`)
    .then((response) => {
      // fetch()는 HTTP 상태와 무관하게 resolve된다 — hub가 DB를 못 읽어
      // 503을 주면 { "error": ... } 모양이라, 체크 없이 바로 TodayUsage로
      // 취급하면 renderUsage가 undefined 필드에서 깨진다.
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json() as Promise<TodayUsage>;
    })
    .then((usage) => renderUsage(app, usage))
    .catch((error: unknown) => renderError(app, String(error)));
}

const app = document.querySelector("#app");
if (app) {
  loadUsage(app);
}
