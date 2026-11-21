import { truncateName } from "../../lib/format";
import {
  carouselItems,
  positionOf,
  stepSelection,
} from "../../lib/goalCarousel";
import { createRouteLink } from "../../router/router";
import styles from "./GoalCarousel.module.css";

export interface GoalCarouselProps {
  /** 목표를 골랐다(null = 목표 전체). */
  onSelect: (id: number | null) => void;
}

export interface GoalCarousel {
  element: HTMLElement;
  /** 목록과 고른 것을 갱신한다. 홈이 15초마다 다시 불러올 때마다 부른다 — 캐러셀 자체는 갈아치워지지 않는다. */
  update: (state: {
    goals: readonly { id: number; name: string }[];
    selectedId: number | null;
  }) => void;
  destroy: () => void;
}

// 좁은 요약 칸에 긴 이름이 넘치지 않게 줄인다(전체 이름은 title과 점 단추의 이름에 있다).
const MAX_NAME_CHARS = 14;

/**
 * 홈 맨 위의 목표 캐러셀: "목표 전체 → 목표 1 → … → 목표 N → (다시) 목표 전체"로 이어지는 원형이다. **자동으로 넘어가지 않는다** — 좌우 화살표, 아래의 점 단추,
 * 키보드(← →)로만 옮긴다(자동 전환은 읽는 중에 화면이 바뀌고 접근성 규칙도 늘어서 쓰지 않는다).
 *
 * 홈은 15초마다 내용을 통째로 다시 그린다. 이 캐러셀은 그 바깥(페이지 맨 위)에 한 번만 붙여 두고 `update`로 목록만 갱신한다 — 그래야 포커스가 갱신에 지워지지 않는다.
 * 순서·이동 규칙은 `lib/goalCarousel`(순수 로직)이 갖고 여기서는 그리기만 한다.
 */
export function createGoalCarousel(props: GoalCarouselProps): GoalCarousel {
  let goals: readonly { id: number; name: string }[] = [];
  let selectedId: number | null = null;

  const root = document.createElement("div");
  root.className = styles.carousel;
  root.setAttribute("role", "group");
  root.setAttribute("aria-roledescription", "캐러셀");
  root.setAttribute("aria-label", "목표 보기");

  const previous = document.createElement("button");
  previous.type = "button";
  previous.className = styles.arrow;
  previous.textContent = "‹";
  previous.setAttribute("aria-label", "이전 목표");

  const next = document.createElement("button");
  next.type = "button";
  next.className = styles.arrow;
  next.textContent = "›";
  next.setAttribute("aria-label", "다음 목표");

  const current = document.createElement("div");
  current.className = styles.current;
  // 사용자가 눌러서 바뀐 것만 알리므로(자동으로 바뀌지 않는다) 스크린 리더에 읽어 준다.
  current.setAttribute("aria-live", "polite");

  const dots = document.createElement("div");
  dots.className = styles.dots;

  const row = document.createElement("div");
  row.className = styles.row;
  row.append(previous, current, next);
  root.append(row, dots);

  function choose(id: number | null): void {
    selectedId = id;
    render();
    props.onSelect(id);
  }

  function step(delta: 1 | -1): void {
    choose(stepSelection(goals, selectedId, delta));
  }

  function render(): void {
    const items = carouselItems(goals);
    const { index, count } = positionOf(goals, selectedId);
    const item = items[index];
    const name = document.createElement("span");
    name.className = styles.name;
    name.textContent = truncateName(item.name, MAX_NAME_CHARS); // 목표 이름은 사용자 입력이라 textContent로만 넣는다
    const position = document.createElement("span");
    position.className = styles.position;
    position.textContent = `${index + 1} / ${count}`;
    // 가운데 칸: 목표 하나를 보는 중이면 누르면 그 목표의 개요 화면으로 가는 링크(손 모양 커서, 올리면 회색), 목표 전체는 갈 곳이 없어 그냥 글자다(평범한 커서).
    let center: HTMLElement;
    if (item.id === null) {
      center = document.createElement("div");
      center.className = `${styles.center} ${styles.plain}`;
      center.title = item.name;
    } else {
      center = createRouteLink({ name: "goal", goalId: item.id });
      center.className = `${styles.center} ${styles.link}`;
      center.title = `${item.name} — 목표 개요 보기`;
    }
    center.append(name, position);
    current.replaceChildren(center);
    // 칸이 하나뿐이면(목표가 없다) 넘길 곳이 없다.
    previous.disabled = count === 1;
    next.disabled = count === 1;
    dots.hidden = count === 1;
    dots.replaceChildren(
      ...items.map((candidate, candidateIndex) => {
        const dot = document.createElement("button");
        dot.type = "button";
        dot.className = styles.dot;
        dot.setAttribute("aria-label", candidate.name);
        dot.title = candidate.name;
        if (candidateIndex === index) {
          dot.setAttribute("aria-current", "true");
        }
        dot.addEventListener("click", () => choose(candidate.id));
        return dot;
      }),
    );
  }

  previous.addEventListener("click", () => step(-1));
  next.addEventListener("click", () => step(1));
  root.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      step(event.key === "ArrowRight" ? 1 : -1);
    }
  });
  render();

  return {
    element: root,
    update(state) {
      goals = state.goals;
      selectedId = state.selectedId;
      render();
    },
    destroy() {
      root.remove();
    },
  };
}
