import { createButton, createButtonGroup } from "./Button";
import styles from "./TripleNav.module.css";

/** 왼쪽·오른쪽 단추 하나의 상태. hint가 null이면 화살표만 있고(이웃 글자 자리가 없다), 문자열이면 화살표 안쪽에 그 글자가 연하게 들어간다(빈 문자열이어도 자리는 남는다). */
export interface NavSide {
  hint: string | null;
  /** 스크린 리더용 단추 이름. */
  ariaLabel: string;
  /** 마우스를 올렸을 때의 툴팁(없으면 빈 문자열). */
  title: string;
  disabled: boolean;
}

export interface TripleNavState {
  previous: NavSide;
  next: NavSide;
}

export interface TripleNavProps {
  /** 가운데 칸. 무엇이든 자유롭게 넣는다(글자, 링크, 단추). 이 컴포넌트는 내용을 모른다. */
  center: HTMLElement;
  /** 단추에 테두리를 둘지(날짜 이동) 말지(목표 캐러셀). 이 컴포넌트가 주는 유일한 모양 선택이다. */
  bordered: boolean;
  /**
   * 화살표와 이웃 글자가 천천히 진해졌다 옅어진다(주의를 끌고 싶은 곳에서만 켠다). 마우스를 올리거나 포커스가 있는 동안에는 애니메이션이 꺼지고
   * 또렷하게 보이며, 움직임 줄이기 설정이면 움직이지 않는다.
   */
  pulse?: boolean;
  onPrevious: () => void;
  onNext: () => void;
  state: TripleNavState;
}

export interface TripleNav {
  element: HTMLElement;
  /** 단추의 글자·이름·비활성 상태를 그 자리에서 바꾼다(단추를 다시 만들지 않아 포커스가 유지된다). */
  update: (state: TripleNavState) => void;
  /** 왼쪽·오른쪽 단추(포커스를 옮겨야 할 때). 한 번 만들면 바뀌지 않는다. */
  previous: HTMLButtonElement;
  next: HTMLButtonElement;
}

/**
 * `[← (이웃 글자)] 가운데 [(이웃 글자) →]` 한 줄. 단추 둘과 자유롭게 채우는 가운데 칸으로 이뤄진다 — 화살표가 가장 바깥, 이웃 글자가 그 안쪽이다.
 * 목표 캐러셀(테두리 없음, 이웃 목표 이름의 앞 두 글자)과 날짜 이동(테두리 있음, 이웃 글자 없음)이 같이 쓴다.
 * 줄 높이는 `--period-row-height`가 정해져 있으면 그 값을 따른다(옆 요소와 높이를 맞추려는 것).
 */
export function createTripleNav(props: TripleNavProps): TripleNav {
  const previous = createSideButton(props.bordered, props.onPrevious);
  const next = createSideButton(props.bordered, props.onNext);

  let root: HTMLElement;
  if (props.bordered) {
    // 테두리를 공유하는 한 덩어리(Button.module.css의 group). 가운데 칸도 그 안에 들어간다.
    root = createButtonGroup([previous, props.center, next]);
  } else {
    root = document.createElement("div");
    root.append(previous, props.center, next);
  }
  root.classList.add(styles.nav);
  if (!props.bordered) {
    root.classList.add(styles.borderless);
  }
  if (props.pulse) {
    root.classList.add(styles.pulse);
  }

  function update(state: TripleNavState): void {
    fill(previous, "←", state.previous, "previous");
    fill(next, "→", state.next, "next");
  }
  update(props.state);
  return { element: root, update, previous, next };
}

function createSideButton(
  bordered: boolean,
  onClick: () => void,
): HTMLButtonElement {
  if (bordered) {
    return createButton({ label: "", onClick });
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = styles.plainButton;
  button.addEventListener("click", onClick);
  return button;
}

/** 단추 안을 [화살표, 이웃 글자](왼쪽) / [이웃 글자, 화살표](오른쪽)로 채운다 — 화살표가 항상 바깥이다. */
function fill(
  button: HTMLButtonElement,
  symbol: string,
  side: NavSide,
  where: "previous" | "next",
): void {
  const arrow = document.createElement("span");
  arrow.className = styles.symbol;
  arrow.setAttribute("aria-hidden", "true");
  arrow.textContent = symbol;
  const parts: HTMLElement[] = [arrow];
  if (side.hint !== null) {
    // 이웃 글자는 사용자 입력일 수 있어 textContent로만 넣는다. 단추 이름은 따로 있어 스크린 리더는 이 글자를 읽지 않는다.
    const hint = document.createElement("span");
    hint.className = styles.hint;
    hint.setAttribute("aria-hidden", "true");
    hint.textContent = side.hint;
    parts.push(hint);
  }
  button.replaceChildren(...(where === "previous" ? parts : parts.reverse()));
  button.setAttribute("aria-label", side.ariaLabel);
  button.title = side.title;
  button.disabled = side.disabled;
}
