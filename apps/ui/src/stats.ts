/**
 * 목록에서 가장 큰 값. 비어 있으면 0이다 — 막대 폭의 기준(가장 큰 total)처럼 "없으면 0"이 자연스러운
 * 곳에 쓴다. `Math.max(...목록)`은 항목이 아주 많으면 인자 개수 한도를 넘어 RangeError가 나는데,
 * 여기는 하나씩 훑어서 목록 크기와 무관하게 동작한다.
 */
export function maxOf<T>(
  items: readonly T[],
  value: (item: T) => number,
): number {
  let max = 0;
  for (const item of items) {
    max = Math.max(max, value(item));
  }
  return max;
}
