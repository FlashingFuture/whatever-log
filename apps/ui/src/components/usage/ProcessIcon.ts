import { iconUrl, siteIconUrl } from "../../api";
import { IconStatusCache } from "../../domain/iconStatus";
import styles from "./ProcessIcon.module.css";

// 아이콘이 없다고 확인되었거나(404) 일시적으로 실패한 프로세스의 기억. 15초마다 차트를 다시
// 그릴 때 같은 이름을 또 요청하지 않고 바로 대체 표시를 그린다(자세한 규칙은 iconStatus.ts).
const status = new IconStatusCache();

// 같은 자리를 프로세스 아이콘과 사이트 아이콘이 함께 쓴다. 이름이 겹칠 일은 없지만 기록은
// 종류별로 따로 둔다(프로세스 "a.com"과 사이트 "a.com"이 서로의 실패를 물려받지 않게).
type IconKind = "process" | "site";
const URL_OF: Record<IconKind, (name: string) => string> = {
  process: iconUrl,
  site: siteIconUrl,
};
const keyOf = (kind: IconKind, name: string): string => `${kind}:${name}`;

// 이름별로 가장 최근에 시작한 확인의 순번. 겹친 확인 중 먼저 보낸 것이 늦게 끝나도 최신
// 결과를 덮어쓰지 않게 한다.
const latestCheck = new Map<string, number>();
let checkSeq = 0;

// 확인 요청이 응답 없이 매달리면 재시도 예약도 실행되지 않으니 제한 시간을 둔다.
const CLASSIFY_TIMEOUT_MS = 5_000;

// 일시적 실패 뒤 같은 아이콘 자리를 다시 시도하는 간격. 횟수에 상한이 있고, 넘으면 대체 글자를
// 유지한다(계속 실패하는데 무한히 두드리지 않게). 상세 화면 제목처럼 한 번만 만들어지고 다시
// 그려지지 않는 자리가 hub 복구 뒤에도 대체 글자로 남지 않게 하려는 것이다.
const RETRY_DELAYS_MS = [10_000, 30_000, 60_000];

type FailureKind = "missing" | "transient";

/**
 * <img>의 error 이벤트는 원인을 알려 주지 않는다 — hub 재시작·503·네트워크 오류도 같은
 * 이벤트다. 그런 일시적 실패까지 "아이콘 없음"으로 굳히면 hub가 돌아와도 대체 글자만
 * 나온다. 그래서 같은 주소를 한 번 더 물어 404(없음)일 때만 missing으로 본다(없음 응답은 hub가
 * 잠시 캐시하게 해 두어서 브라우저 캐시에서 바로 나오는 경우가 많다).
 */
async function classifyFailure(url: string): Promise<FailureKind> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CLASSIFY_TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response.status === 404 ? "missing" : "transient";
  } catch {
    return "transient"; // 연결 실패·시간 초과 등 — 없는 게 아니라 못 물어본 것
  } finally {
    clearTimeout(timer);
  }
}

function createFallback(name: string, large: boolean): HTMLSpanElement {
  const fallback = document.createElement("span");
  fallback.className = `${styles.icon} ${styles.fallback}${large ? ` ${styles.large}` : ""}`;
  fallback.textContent = name.charAt(0);
  fallback.setAttribute("aria-hidden", "true");
  return fallback;
}

function createImage(
  kind: IconKind,
  name: string,
  large: boolean,
  attempt: number,
): HTMLImageElement {
  const key = keyOf(kind, name);
  const image = document.createElement("img");
  image.className = `${styles.icon}${large ? ` ${styles.large}` : ""}`;
  image.alt = "";
  image.decoding = "async";
  image.src = URL_OF[kind](name);
  image.addEventListener("load", () => status.clear(key), { once: true });
  image.addEventListener(
    "error",
    () => {
      // 일단 대체 글자를 보여 주고, 원인을 확인해 기억한다.
      const fallback = createFallback(name, large);
      image.replaceWith(fallback);
      const check = ++checkSeq;
      latestCheck.set(key, check);
      void classifyFailure(image.src).then((failure) => {
        if (latestCheck.get(key) !== check) {
          return;
        }
        status.record(key, failure, Date.now());
        if (failure === "transient" && attempt < RETRY_DELAYS_MS.length) {
          setTimeout(
            () => retry(fallback, kind, name, large, attempt + 1),
            RETRY_DELAYS_MS[attempt],
          );
        }
      });
    },
    { once: true },
  );
  return image;
}

function retry(
  fallback: HTMLElement,
  kind: IconKind,
  name: string,
  large: boolean,
  attempt: number,
): void {
  // 차트가 다시 그려져 이 자리가 이미 사라졌다면, 새 자리가 스스로 판단한다.
  if (!fallback.isConnected) {
    return;
  }
  fallback.replaceWith(createImage(kind, name, large, attempt));
}

/**
 * 프로세스 아이콘. hub에서 받아 보여주고, 없거나 실패하면 이름 첫 글자 칸으로
 * 대신한다. 이름은 이미 옆에 글자로 나오니 이미지는 장식이다(alt="").
 */
export function createProcessIcon(
  name: string,
  { large = false }: { large?: boolean } = {},
): HTMLElement {
  return createIcon("process", name, large);
}

/** 사이트(도메인) 아이콘. 같은 규칙으로 불러오고, 없으면 도메인 첫 글자 칸으로 대신한다. */
export function createSiteIcon(
  domain: string,
  { large = false }: { large?: boolean } = {},
): HTMLElement {
  return createIcon("site", domain, large);
}

function createIcon(kind: IconKind, name: string, large: boolean): HTMLElement {
  const now = Date.now();
  const remaining = status.remainingMs(keyOf(kind, name), now);
  if (remaining === null) {
    return createImage(kind, name, large, 0);
  }
  // 기록이 만료되는 때 한 번 다시 시도한다 — 상세 화면 제목처럼 다시 그려지지 않는 자리가
  // 대체 글자로 남지 않게(분리된 자리는 retry가 알아서 건너뛴다).
  const fallback = createFallback(name, large);
  setTimeout(() => retry(fallback, kind, name, large, 1), remaining);
  return fallback;
}
