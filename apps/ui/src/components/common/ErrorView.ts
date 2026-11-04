import { createButton } from "./Button";

/** 불러오기 실패 안내 + 다시 시도 버튼. */
export function createErrorView(
  message: string,
  onRetry: () => void,
): HTMLElement {
  const container = document.createElement("div");

  const error = document.createElement("p");
  error.textContent = `불러오지 못했습니다: ${message}`;

  // hub가 콜드 스타트로 늦게 뜨면 desktop은 이 화면을 보여준 채로 창을 연다
  // (apps/desktop/__main__.py의 _wait_for_hub_port 타임아웃 처리). hub는
  // 백그라운드에서 계속 재시도되니, 다시 열지 않고도 재시도할 방법이 있어야
  // 한다.
  container.append(
    error,
    createButton({ label: "다시 시도", onClick: onRetry }),
  );
  return container;
}
