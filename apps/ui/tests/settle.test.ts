import assert from "node:assert/strict";
import { mock, test } from "node:test";

import { settleWithin } from "../src/settle.ts";

test("제한 시간 안에 끝나면 그 값을 돌려준다", async () => {
  assert.equal(await settleWithin(Promise.resolve("ok"), 1_000), "ok");
});

test("제한 시간이 지나면 undefined를 돌려주고, 원래 promise는 계속 진행된다", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    let finish: (value: string) => void = () => {};
    const slow = new Promise<string>((resolve) => {
      finish = resolve;
    });

    const waiting = settleWithin(slow, 300);
    mock.timers.tick(300);

    assert.equal(await waiting, undefined);
    finish("late");
    assert.equal(await slow, "late"); // 버려지지 않고 이어서 쓸 수 있다
  } finally {
    mock.timers.reset();
  }
});

test("먼저 끝나면 시간 제한 타이머를 남기지 않는다", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    await settleWithin(Promise.resolve(1), 300);

    // 타이머가 정리됐다면 시간이 흘러도 아무 일도 일어나지 않는다.
    assert.doesNotThrow(() => mock.timers.tick(1_000));
  } finally {
    mock.timers.reset();
  }
});
