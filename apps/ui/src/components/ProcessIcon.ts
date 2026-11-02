import { iconUrl } from "../api";
import styles from "./ProcessIcon.module.css";

// 아이콘이 없다고 확인된 프로세스와 그 시각. 15초마다 차트를 다시 그릴 때 같은 이름을
// 또 요청하지 않고 바로 대체 표시를 그린다(hub의 404도 잠시 캐시되지만, 요청 자체를
// 안 보내는 게 더 싸다). 영구히 기억하지는 않는다 — recorder가 나중에 경로를
// 기록하거나(옛 DB 마이그레이션 직후 등) 새로 실행된 앱이 생길 수 있어서, hub가
// "없음"을 캐시하는 시간(5분)과 같이 지나면 다시 시도한다.
const MISSING_RETRY_MS = 5 * 60 * 1000;
const missing = new Map<string, number>();

function isKnownMissing(name: string): boolean {
  const since = missing.get(name);
  if (since === undefined) {
    return false;
  }
  if (Date.now() - since >= MISSING_RETRY_MS) {
    missing.delete(name);
    return false;
  }
  return true;
}

/**
 * <img>의 error 이벤트는 원인을 알려 주지 않는다 — hub 재시작·503·네트워크 오류도 같은
 * 이벤트다. 그런 일시적 실패까지 "아이콘 없음"으로 5분 동안 기억하면 hub가 돌아와도
 * 대체 글자만 나온다. 그래서 같은 주소를 한 번 더 물어 404(없음)일 때만 기억한다(없음
 * 응답은 hub가 잠시 캐시하게 해 두어서 브라우저 캐시에서 바로 나오는 경우가 많다).
 */
async function confirmMissing(url: string): Promise<boolean> {
  try {
    return (await fetch(url)).status === 404;
  } catch {
    return false; // 연결 실패 등 — 없는 게 아니라 못 물어본 것
  }
}

function createFallback(name: string, large: boolean): HTMLSpanElement {
  const fallback = document.createElement("span");
  fallback.className = `${styles.icon} ${styles.fallback}${large ? ` ${styles.large}` : ""}`;
  fallback.textContent = name.charAt(0);
  fallback.setAttribute("aria-hidden", "true");
  return fallback;
}

/**
 * 프로세스 아이콘. hub에서 받아 보여주고, 없거나 실패하면 이름 첫 글자 칸으로
 * 대신한다. 이름은 이미 옆에 글자로 나오니 이미지는 장식이다(alt="").
 */
export function createProcessIcon(
  name: string,
  { large = false }: { large?: boolean } = {},
): HTMLElement {
  if (isKnownMissing(name)) {
    return createFallback(name, large);
  }
  const image = document.createElement("img");
  image.className = `${styles.icon}${large ? ` ${styles.large}` : ""}`;
  image.alt = "";
  image.decoding = "async";
  image.src = iconUrl(name);
  image.addEventListener(
    "error",
    () => {
      // 일단 대체 글자를 보여 주고, 진짜 "없음"일 때만 기억한다.
      image.replaceWith(createFallback(name, large));
      void confirmMissing(image.src).then((isMissing) => {
        if (isMissing) {
          missing.set(name, Date.now());
        }
      });
    },
    { once: true },
  );
  return image;
}
