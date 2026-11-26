import assert from "node:assert/strict";
import { test } from "node:test";

import { HOME } from "../../src/router/router.ts";
import { hasBack } from "../../src/router/routes.ts";

test("홈에는 뒤로 가기가 없고, 프로세스 상세·목표 개요에는 있다", () => {
  assert.equal(hasBack(HOME), false);
  assert.equal(hasBack({ name: "process", process: "chrome.exe" }), true);
  assert.equal(hasBack({ name: "goal", goalId: 3 }), true);
});
