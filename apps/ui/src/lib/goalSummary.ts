import { processKey } from "./processPick.ts";

/** 가장 길게 수행한 프로세스와 그 활성 시간(초). */
export interface TopProcess {
  process: string;
  active_seconds: number;
}

/**
 * 홈 요약에 "가장 길게 수행한 프로세스"를 어떻게 보여 줄지:
 * - same: 목표 중 가장 길게 수행한 프로세스가 실제로도 가장 길게 수행한 프로세스와 같다 → 하나만 보인다.
 * - goalAndActual: 둘이 다르다 → 목표 중 최장과 실제 최장을 둘 다 보인다.
 * - actualOnly: 목표 쪽 프로세스가 없다(목표가 없거나 연결·수행이 없음) → 실제 최장만 보인다.
 */
export type TopBlocks =
  | { kind: "same"; top: TopProcess }
  | { kind: "goalAndActual"; goalTop: TopProcess; actualTop: TopProcess | null }
  | { kind: "actualOnly"; actualTop: TopProcess | null };

/** 두 값을 비교해 위 세 가지 중 하나로 정한다(프로세스 이름은 대소문자를 구분하지 않고 같은지 본다). */
export function chooseTopBlocks(
  goalTop: TopProcess | null,
  actualTop: TopProcess | null,
): TopBlocks {
  if (goalTop === null) {
    return { kind: "actualOnly", actualTop };
  }
  if (
    actualTop !== null &&
    processKey(goalTop.process) === processKey(actualTop.process)
  ) {
    return { kind: "same", top: actualTop };
  }
  return { kind: "goalAndActual", goalTop, actualTop };
}
