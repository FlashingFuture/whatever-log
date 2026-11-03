import assert from "node:assert/strict";
import { test } from "node:test";

import { formatDuration, truncateName } from "../src/format.ts";

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

test("이름은 글자 수를 넘을 때만 앞부분 + …로 줄인다(보조 평면 글자도 하나로 센다)", () => {
  assert.equal(truncateName("chrome.exe", 10), "chrome.exe");
  assert.equal(truncateName("Hearthstone.exe", 10), "Hearthston…");
  assert.equal(truncateName("메모장메모장메모장메모장.exe", 4), "메모장메…");
  assert.equal(truncateName("😀😀😀😀😀😀", 4), "😀😀😀😀…");
  assert.equal(truncateName("", 10), "");
});
