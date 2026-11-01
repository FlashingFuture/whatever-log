import assert from "node:assert/strict";
import { test } from "node:test";

import { isScrollKey } from "../src/scroll.ts";

test("페이지를 스크롤하는 키만 복원을 멈춘다", () => {
  for (const key of [
    "ArrowUp",
    "ArrowDown",
    "PageUp",
    "PageDown",
    "Home",
    "End",
    " ",
  ]) {
    assert.equal(isScrollKey(key), true, key);
  }
  for (const key of [
    "Tab",
    "Enter",
    "Escape",
    "a",
    "Shift",
    "ArrowLeft",
    "ArrowRight",
  ]) {
    assert.equal(isScrollKey(key), false, key);
  }
});
