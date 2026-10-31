import assert from "node:assert/strict";
import { test } from "node:test";

import { HOME, isSameRoute, parseRoute, routeHref } from "../src/router.ts";

test("홈은 #/ 이고 모르는 주소도 홈으로 본다", () => {
  assert.equal(routeHref(HOME), "#/");
  assert.deepEqual(parseRoute(""), HOME);
  assert.deepEqual(parseRoute("#/"), HOME);
  assert.deepEqual(parseRoute("#/nowhere"), HOME);
});

test("프로세스 주소는 이름을 인코딩해서 왕복한다(공백·점·슬래시·한글)", () => {
  for (const process of [
    "chrome.exe",
    "Docker Desktop.exe",
    "a/b.exe",
    "메모장.exe",
  ]) {
    const route = { name: "process", process } as const;
    assert.deepEqual(parseRoute(routeHref(route)), route);
  }
  assert.equal(
    routeHref({ name: "process", process: "Docker Desktop.exe" }),
    "#/process/Docker%20Desktop.exe",
  );
});

test("깨진 인코딩이나 빈 이름은 홈으로", () => {
  assert.deepEqual(parseRoute("#/process/%E0%A4%A"), HOME);
  assert.deepEqual(parseRoute("#/process/"), HOME);
});

test("같은 경로 판정", () => {
  assert.equal(isSameRoute(HOME, parseRoute("")), true);
  assert.equal(
    isSameRoute(
      { name: "process", process: "a" },
      { name: "process", process: "b" },
    ),
    false,
  );
});
