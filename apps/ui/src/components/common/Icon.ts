const SVG_NS = "http://www.w3.org/2000/svg";

// 24x24 격자의 선(stroke) 아이콘. 경로 여러 개는 "|"로 나눈다. 외부 아이콘 라이브러리 없이 필요한 것만 둔다.
const PATHS = {
  plus: "M12 5v14|M5 12h14",
  pencil: "M4 20h4L19 9l-4-4L4 16z|M13.5 6.5l4 4",
  trash: "M5 7h14|M10 11v6|M14 11v6|M6.5 7l1 12h9l1-12|M9 7V4h6v3",
  close: "M6 6l12 12|M18 6L6 18",
  back: "M15 5l-7 7 7 7",
} as const;

export type IconName = keyof typeof PATHS;

/** 글자색(currentColor)을 따르는 선 아이콘. 장식이라 스크린 리더에는 숨기고, 뜻은 버튼의 이름이 맡는다. */
export function createIcon(name: IconName, size = 18): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const d of PATHS[name].split("|")) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}
