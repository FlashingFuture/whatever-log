import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDuration } from "../src/format.ts";

test("1분 미만은 초 단위, 0은 0분", () => {
  assert.equal(formatDuration(0), "0분");
  assert.equal(formatDuration(0.2), "1초");
  assert.equal(formatDuration(15), "15초");
  assert.equal(formatDuration(59.4), "59초");
});

test("1분 이상은 분 단위로 반올림, 1시간 이상은 시간+분", () => {
  assert.equal(formatDuration(60), "1분");
  assert.equal(formatDuration(89), "1분");
  assert.equal(formatDuration(150), "3분");
  assert.equal(formatDuration(3600), "1시간 0분");
  assert.equal(formatDuration(3725), "1시간 2분");
});
