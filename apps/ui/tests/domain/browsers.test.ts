import assert from "node:assert/strict";
import { test } from "node:test";

import { isBrowserProcess } from "../../src/domain/browsers.ts";

test("사이트를 기록하는 브라우저 프로세스만 브라우저로 본다", () => {
  for (const name of ["chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe"]) {
    assert.equal(isBrowserProcess(name), true, name);
  }
  for (const name of ["Code.exe", "firefox.exe", "Chrome.exe", ""]) {
    assert.equal(isBrowserProcess(name), false, name);
  }
});
