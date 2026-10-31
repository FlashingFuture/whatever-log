import { iconUrl } from "../api";
import { injectStyle } from "../styles/injectStyle";
import { theme } from "../theme";

injectStyle(
  "process-icon",
  `
  .process-icon {
    flex: none;
    width: 1.25rem;
    height: 1.25rem;
    border-radius: 4px;
    object-fit: contain;
  }
  .process-icon-large {
    width: 2rem;
    height: 2rem;
    border-radius: 6px;
  }
  .process-icon-fallback {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: ${theme.colors.track};
    color: ${theme.colors.textMuted};
    font-size: 0.7rem;
    text-transform: uppercase;
  }
`,
);

// 아이콘이 없다고 확인된 프로세스. 15초마다 차트를 다시 그릴 때 같은 이름을
// 또 요청하지 않고 바로 대체 표시를 그린다(hub의 404도 잠시 캐시되지만, 요청 자체를
// 안 보내는 게 더 싸다). 새로고침하면 비워진다 — 나중에 경로가 기록될 수 있으니
// 영구히 기억하지는 않는다.
const missing = new Set<string>();

function createFallback(name: string, sizeClass: string): HTMLSpanElement {
  const fallback = document.createElement("span");
  fallback.className = `process-icon process-icon-fallback${sizeClass}`;
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
  const sizeClass = large ? " process-icon-large" : "";
  if (missing.has(name)) {
    return createFallback(name, sizeClass);
  }
  const image = document.createElement("img");
  image.className = `process-icon${sizeClass}`;
  image.alt = "";
  image.decoding = "async";
  image.src = iconUrl(name);
  image.addEventListener(
    "error",
    () => {
      missing.add(name);
      image.replaceWith(createFallback(name, sizeClass));
    },
    { once: true },
  );
  return image;
}
