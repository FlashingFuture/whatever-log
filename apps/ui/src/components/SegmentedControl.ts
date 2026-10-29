import { injectStyle } from "../styles/injectStyle";
import { createButton } from "./Button";

injectStyle(
  "segmented-control",
  `
  .segmented-control {
    display: inline-flex;
    gap: 0.25rem;
  }
`,
);

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export interface SegmentedControlProps<T extends string> {
  options: SegmentedOption<T>[];
  selected: T;
  onChange: (value: T) => void;
  /** 그룹 전체의 스크린 리더용 이름(예: "조회 단위"). */
  ariaLabel: string;
}

/** 여러 값 중 하나를 고르는 버튼 묶음. 값의 종류와 무관하게 재사용한다. */
export function createSegmentedControl<T extends string>(
  props: SegmentedControlProps<T>,
): HTMLElement {
  const group = document.createElement("div");
  group.className = "segmented-control";
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", props.ariaLabel);

  for (const option of props.options) {
    group.append(
      createButton({
        label: option.label,
        pressed: option.value === props.selected,
        onClick: () => {
          if (option.value !== props.selected) {
            props.onChange(option.value);
          }
        },
      }),
    );
  }
  return group;
}
