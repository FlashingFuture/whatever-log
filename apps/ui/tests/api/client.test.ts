import assert from "node:assert/strict";
import { test } from "node:test";

import { requestTimeoutMs } from "../../src/api/client.ts";

const DAY_MS = 24 * 60 * 60 * 1000;

test("일/주 조회는 짧은 제한 시간, 월 조회는 긴 제한 시간", () => {
  assert.equal(requestTimeoutMs(DAY_MS), 10_000);
  assert.equal(requestTimeoutMs(7 * DAY_MS), 10_000);
  assert.equal(requestTimeoutMs(28 * DAY_MS), 60_000);
  assert.equal(requestTimeoutMs(31 * DAY_MS), 60_000);
});
