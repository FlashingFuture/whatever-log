const injectedIds = new Set<string>();

/**
 * 컴포넌트 파일 안에 그 컴포넌트의 CSS를 같이 두는 가벼운 CSS-in-JS
 * 패턴이다 — 라이브러리(styled-components 등)를 들이지 않고, 컴포넌트가
 * import될 때 한 번만 <style> 태그로 주입한다. 빌드 타임 추출이나 클래스명
 * 스코프 격리 같은 건 하지 않는다 — 화면이 하나뿐인 지금 수준엔 그 정도로
 * 충분하다.
 */
export function injectStyle(id: string, css: string): void {
  if (injectedIds.has(id)) {
    return;
  }
  injectedIds.add(id);

  const style = document.createElement("style");
  style.dataset.component = id;
  style.textContent = css;
  document.head.append(style);
}
