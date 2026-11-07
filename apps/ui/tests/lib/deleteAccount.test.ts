import assert from "node:assert/strict";
import { test } from "node:test";

import { canConfirmDelete, outcomeLines } from "../../src/lib/deleteAccount.ts";

const EMAIL = "a@example.com";

test("이해했다고 체크하지 않으면 이메일이 맞아도 삭제할 수 없다", () => {
  assert.equal(canConfirmDelete(false, EMAIL, EMAIL), false);
});

test("이메일을 직접 입력해 맞춰야 삭제할 수 있다(대소문자·앞뒤 공백은 무시)", () => {
  assert.equal(canConfirmDelete(true, "", EMAIL), false);
  assert.equal(canConfirmDelete(true, "b@example.com", EMAIL), false);
  assert.equal(canConfirmDelete(true, "a@example.co", EMAIL), false);
  assert.equal(canConfirmDelete(true, "a@example.com", EMAIL), true);
  assert.equal(canConfirmDelete(true, "  A@Example.COM ", EMAIL), true);
});

test("이메일을 알 수 없는 로그인은 체크만 요구한다", () => {
  assert.equal(canConfirmDelete(true, "", null), true);
  assert.equal(canConfirmDelete(false, "", null), false);
});

test("모두 정리됐으면 서버 삭제·로그아웃·이 PC에 남는 것을 알린다", () => {
  const lines = outcomeLines({
    deleted_on_server: true,
    signed_out: true,
    connections_cleared: true,
  });

  assert.equal(lines.length, 3);
  assert.match(lines[0], /서버의 계정과/);
  assert.match(lines[1], /로그인 정보도 지웠어요/);
  assert.match(lines[2], /이 PC의 기록과 목표.*그대로/);
});

test("이 PC의 로그인 정보를 지우지 못했으면 서버 삭제 사실을 먼저 말하고 로그아웃을 안내한다", () => {
  const lines = outcomeLines({
    deleted_on_server: true,
    signed_out: false,
    connections_cleared: true,
  });

  assert.match(lines[0], /서버의 계정과/);
  assert.match(lines[1], /로그아웃/);
});

test("서버 연결 표시를 정리하지 못한 경우도 알린다", () => {
  const lines = outcomeLines({
    deleted_on_server: true,
    signed_out: true,
    connections_cleared: false,
  });

  assert.ok(lines.some((line) => line.includes("연결 표시")));
});
