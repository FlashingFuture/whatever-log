import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ALL_GOALS_LABEL,
  carouselItems,
  positionOf,
  stepSelection,
} from "../../src/lib/goalCarousel.ts";

const GOALS = [
  { id: 4, name: "공부" },
  { id: 9, name: "운동" },
  { id: 2, name: "독서" },
];

test("칸은 맨 앞이 목표 전체이고 목표가 만든 순서대로 이어진다", () => {
  assert.deepEqual(carouselItems(GOALS), [
    { id: null, name: ALL_GOALS_LABEL },
    { id: 4, name: "공부" },
    { id: 9, name: "운동" },
    { id: 2, name: "독서" },
  ]);
  assert.deepEqual(carouselItems([]), [{ id: null, name: ALL_GOALS_LABEL }]);
});

test("다음으로 넘기면 전체 → 목표들 → 다시 전체로 돈다", () => {
  let selected: number | null = null;
  const visited: (number | null)[] = [];
  for (let step = 0; step < 5; step += 1) {
    selected = stepSelection(GOALS, selected, 1);
    visited.push(selected);
  }
  assert.deepEqual(visited, [4, 9, 2, null, 4]);
});

test("이전으로 넘기면 전체에서 마지막 목표로 돌아간다", () => {
  assert.equal(stepSelection(GOALS, null, -1), 2);
  assert.equal(stepSelection(GOALS, 2, -1), 9);
  assert.equal(stepSelection(GOALS, 4, -1), null);
});

test("목표가 없으면 어느 쪽으로 넘겨도 목표 전체이다", () => {
  assert.equal(stepSelection([], null, 1), null);
  assert.equal(stepSelection([], null, -1), null);
});

test("고른 목표가 지워졌으면 목표 전체에서 시작한다", () => {
  assert.deepEqual(positionOf(GOALS, 99), { index: 0, count: 4 });
  assert.equal(stepSelection(GOALS, 99, 1), 4);
  assert.equal(stepSelection(GOALS, 99, -1), 2);
});

test("위치는 0부터이고 칸 수에는 목표 전체가 들어 있다", () => {
  assert.deepEqual(positionOf(GOALS, null), { index: 0, count: 4 });
  assert.deepEqual(positionOf(GOALS, 9), { index: 2, count: 4 });
});
