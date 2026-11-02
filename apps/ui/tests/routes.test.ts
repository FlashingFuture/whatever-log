import assert from "node:assert/strict";
import { test } from "node:test";

import { HOME } from "../src/router.ts";
import { layoutOf } from "../src/routes.ts";

test("홈은 돌아가기 없는 레이아웃, 프로세스 상세는 돌아가기 레이아웃", () => {
  assert.equal(layoutOf(HOME), "plain");
  assert.equal(layoutOf({ name: "process", process: "chrome.exe" }), "back");
});
