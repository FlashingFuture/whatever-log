export function renderErrorView(
  app: Element,
  message: string,
  onRetry: () => void,
): void {
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
  retry.addEventListener("click", onRetry);

  app.append(error, retry);
}
