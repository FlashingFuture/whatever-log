import { truncateName } from "../../lib/format";
import {
  carouselItems,
  headChars,
  neighborsOf,
  positionOf,
  stepSelection,
} from "../../lib/goalCarousel";
import { createRouteLink } from "../../router/router";
import { createTripleNav, type TripleNavState } from "../common/TripleNav";
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

// 좁은 요약 칸에 긴 이름이 넘치지 않게 줄인다(전체 이름은 title에 있다).
const MAX_NAME_CHARS = 14;

/**
 * 홈 맨 위의 목표 캐러셀: "목표 전체 → 목표 1 → … → 목표 N → (다시) 목표 전체"로 이어지는 원형이다. **자동으로 넘어가지 않는다** — 좌우 화살표와
 * 키보드(← →)로만 옮긴다(자동 전환은 읽는 중에 화면이 바뀌고 접근성 규칙도 늘어서 쓰지 않는다). 화살표 바깥에는 이웃 목표를 **연하게 엿보여** 준다:
 * 양쪽 모두 이웃 칸 이름의 **앞 두 글자** — **화살표가 가장 바깥, 연한 글자가 그 안쪽**이다(힌트이자 화살표 단추의 일부라 눌러도 그쪽으로 간다). 단추 둘과 가운데 칸의 틀은 날짜 이동과 같은 `TripleNav`(테두리 없는 쪽)다.
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

  const current = document.createElement("div");
  current.className = styles.current;
  // 사용자가 눌러서 바뀐 것만 알리므로(자동으로 바뀌지 않는다) 스크린 리더에 읽어 준다.
  current.setAttribute("aria-live", "polite");

  const nav = createTripleNav({
    center: current,
    bordered: false,
    pulse: true,
    onPrevious: () => step(-1),
    onNext: () => step(1),
    state: navState(),
  });
  root.append(nav.element);

  /** 지금 목표와 이웃에 맞춘 단추 상태. 칸이 하나뿐이면(목표가 없다) 넘길 곳이 없어 비활성이고 이웃 글자는 비어 있다. */
  function navState(): TripleNavState {
    const alone = goals.length === 0;
    const { previous, next } = neighborsOf(goals, selectedId);
    return {
      previous: {
        hint: alone ? "" : headChars(previous.name),
        ariaLabel: alone ? "이전 목표" : `이전 목표: ${previous.name}`,
        title: alone ? "" : previous.name,
        disabled: alone,
      },
      next: {
        hint: alone ? "" : headChars(next.name),
        ariaLabel: alone ? "다음 목표" : `다음 목표: ${next.name}`,
        title: alone ? "" : next.name,
        disabled: alone,
      },
    };
  }

  function choose(id: number | null): void {
    selectedId = id;
    render();
    props.onSelect(id);
  }

  // 마지막으로 넘긴 방향. 가운데 칸에 있던 포커스를 단추로 돌려보낼 때 그쪽 단추를 고른다.
  let lastDelta: 1 | -1 = 1;
  // 지금 그려 둔 가운데 칸의 내용 키(선택·이름·위치). 같으면 가운데 칸을 다시 만들지 않는다.
  let centerKey = "";

  function step(delta: 1 | -1): void {
    lastDelta = delta;
    choose(stepSelection(goals, selectedId, delta));
  }

  /** 가운데 칸: 목표 하나를 보는 중이면 누르면 그 목표의 개요 화면으로 가는 링크(손 모양 커서, 올리면 회색), 목표 전체는 갈 곳이 없어 그냥 글자다(평범한 커서). */
  function createCenter(
    item: { id: number | null; name: string },
    index: number,
    count: number,
  ): HTMLElement {
    const name = document.createElement("span");
    name.className = styles.name;
    name.textContent = truncateName(item.name, MAX_NAME_CHARS); // 목표 이름은 사용자 입력이라 textContent로만 넣는다
    let center: HTMLElement;
    if (item.id === null) {
      center = document.createElement("div");
      center.className = `${styles.center} ${styles.plain}`;
      center.title = item.name;
    } else {
      center = createRouteLink({ name: "goal", goalId: item.id });
      center.className = `${styles.center} ${styles.link}`;
      center.title = `${item.name} — 목표 개요 보기`;
      // 위치(몇 번째 중 몇 개)는 화면에 글자로 보이지 않는다 — 스크린 리더에는 알린다.
      center.setAttribute(
        "aria-label",
        `${item.name}, ${count}개 중 ${index + 1}번째. 목표 개요 보기`,
      );
    }
    center.append(name);
    return center;
  }

  function render(): void {
    const items = carouselItems(goals);
    const { index, count } = positionOf(goals, selectedId);
    const item = items[index];
    // 홈이 15초마다 목록을 다시 넘겨도(update) 같은 칸이면 가운데 칸을 그대로 둔다 — 다시 만들면 포커스가 있던 링크가 사라져 키보드 이동이 끊긴다.
    const key = `${item.id}|${item.name}|${index}|${count}`;
    if (key !== centerKey) {
      // 포커스가 가운데 칸 안에 있었을 때만(밖의 포커스는 가져오지 않는다) 새 가운데 링크로, 링크가 없는 칸(목표 전체)이면 넘긴 방향의 단추로 옮긴다.
      const hadFocus = current.contains(document.activeElement);
      const center = createCenter(item, index, count);
      current.replaceChildren(center);
      centerKey = key;
      if (hadFocus) {
        (center instanceof HTMLAnchorElement
          ? center
          : lastDelta === -1
            ? nav.previous
            : nav.next
        ).focus();
      }
    }
    nav.update(navState());
  }

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
