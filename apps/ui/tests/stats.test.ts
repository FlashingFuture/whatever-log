import assert from "node:assert/strict";
import { test } from "node:test";

import { maxOf } from "../src/stats.ts";

test("0 이상의 가장 큰 값을, 비어 있거나 음수뿐이면 0을 돌려준다(바닥이 0)", () => {
  assert.equal(
    maxOf([-5, -2], (value) => value),
    0,
  );
  assert.equal(
    maxOf([{ v: 3 }, { v: 9 }, { v: 5 }], (item) => item.v),
    9,
  );
  assert.equal(
    maxOf([], () => 1),
    0,
  );
  assert.equal(
    maxOf([{ v: 0 }], (item) => item.v),
    0,
  );
});

test("인자 개수 한도를 넘는 큰 목록도 처리한다(Math.max(...목록)은 RangeError)", () => {
  const items = Array.from({ length: 500_000 }, (_, index) => index);

  assert.throws(() => Math.max(...items), RangeError);
  assert.equal(
    maxOf(items, (value) => value),
    499_999,
  );
});
