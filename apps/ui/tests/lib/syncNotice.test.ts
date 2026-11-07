import assert from "node:assert/strict";
import { test } from "node:test";

import { syncNotice } from "../../src/lib/syncNotice.ts";

test("로그인하지 않았으면 안내하지 않는다(서버와 상관없다)", () => {
  assert.equal(syncNotice({ phase: "signedOut", syncEnabled: false }), null);
  assert.equal(syncNotice({ phase: "unavailable", syncEnabled: true }), null);
});

test("로그인했지만 동기화를 켜지 않았으면 이 목표가 서버로 가지 않는다고 알리고 켜는 길을 안내한다", () => {
  const text = syncNotice({ phase: "signedIn", syncEnabled: false }) ?? "";

  assert.match(text, /서버로 가지 않아요/);
  assert.match(text, /목표 동기화/);
});

test("동기화를 켰으면 서버에 저장되는 값과, 프로세스·사이트는 이 PC에만 있다고 알린다", () => {
  const text = syncNotice({ phase: "signedIn", syncEnabled: true }) ?? "";

  assert.match(text, /이름·목표 시간·요일/);
  assert.match(text, /이 PC에만/);
  assert.doesNotMatch(text, /서버로 가지 않아요/);
});
