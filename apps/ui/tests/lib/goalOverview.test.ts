import assert from "node:assert/strict";
import { test } from "node:test";

import {
  domainsByBrowser,
  goalProcessRows,
  goalSiteRows,
  goalTargets,
} from "../../src/lib/goalOverview.ts";

const usage = (process: string, active: number) => ({
  process,
  active_seconds: active,
  idle_seconds: 0,
  background_seconds: 0,
  total_seconds: active,
});

test("연결한 프로세스만 서버가 준 순서(활성 시간순) 그대로 고른다", () => {
  const rows = goalProcessRows(
    ["a.exe", "c.exe"],
    [usage("b.exe", 90), usage("c.exe", 50), usage("a.exe", 10)],
  );
  assert.deepEqual(
    rows.map((row) => row.process),
    ["c.exe", "a.exe"],
  );
});

test("기록이 없는 연결 프로세스는 0으로 뒤에 붙는다(연결한 순서, 중복 없이)", () => {
  const rows = goalProcessRows(
    ["z.exe", "a.exe", "m.exe", "z.exe"],
    [usage("a.exe", 5)],
  );
  assert.deepEqual(
    rows.map((row) => [row.process, row.total_seconds]),
    [
      ["a.exe", 5],
      ["z.exe", 0],
      ["m.exe", 0],
    ],
  );
});

test("연결한 프로세스가 없으면 빈 목록", () => {
  assert.deepEqual(goalProcessRows([], [usage("a.exe", 5)]), []);
});

const site = (domain: string, active: number) => ({
  domain,
  active_seconds: active,
  idle_seconds: 0,
  total_seconds: active,
});

test("연결한 사이트만 활성 시간순으로 고르고 기록 없는 도메인은 0으로 뒤에 붙인다", () => {
  const rows = goalSiteRows(
    ["x.com", "y.com", "none.com"],
    [site("y.com", 30), site("other.com", 99), site("x.com", 60)],
  );
  assert.deepEqual(
    rows.map((row) => [row.domain, row.active_seconds]),
    [
      ["x.com", 60],
      ["y.com", 30],
      ["none.com", 0],
    ],
  );
});

test("사이트 동률이면 받은 순서를 지킨다", () => {
  const rows = goalSiteRows(
    ["a.com", "b.com"],
    [site("b.com", 5), site("a.com", 5)],
  );
  assert.deepEqual(
    rows.map((row) => row.domain),
    ["b.com", "a.com"],
  );
});

test("연결한 사이트를 브라우저별로 묶고 같은 도메인은 한 번만 담는다", () => {
  const grouped = domainsByBrowser([
    { browser: "chrome.exe", domain: "a.com" },
    { browser: "msedge.exe", domain: "b.com" },
    { browser: "chrome.exe", domain: "c.com" },
    { browser: "chrome.exe", domain: "a.com" },
  ]);
  assert.deepEqual(
    [...grouped],
    [
      ["chrome.exe", ["a.com", "c.com"]],
      ["msedge.exe", ["b.com"]],
    ],
  );
});

test("프로세스와 사이트를 한 목록으로 합쳐 활성 시간순으로 놓고 동률은 프로세스·받은 순서를 지킨다", () => {
  const targets = goalTargets(
    [usage("a.exe", 10), usage("z.exe", 0)],
    [
      { browser: "chrome.exe", ...site("x.com", 30) },
      { browser: "chrome.exe", ...site("none.com", 0) },
      { browser: "msedge.exe", ...site("y.com", 10) },
    ],
  );
  assert.deepEqual(
    targets.map((target) =>
      target.kind === "process"
        ? target.process
        : `${target.browser}/${target.domain}`,
    ),
    [
      "chrome.exe/x.com",
      "a.exe",
      "msedge.exe/y.com",
      "z.exe",
      "chrome.exe/none.com",
    ],
  );
});

test("사이트 칸은 백그라운드 시간 0으로 채우고 전체 시간은 그대로 둔다", () => {
  const [target] = goalTargets(
    [],
    [{ browser: "chrome.exe", ...site("x.com", 30) }],
  );
  assert.equal(target.kind, "site");
  assert.deepEqual(target.usage, {
    active_seconds: 30,
    idle_seconds: 0,
    total_seconds: 30,
    background_seconds: 0,
  });
});

test("대소문자만 다른 프로세스 이름은 같은 프로세스로 보고 합친다(0 행을 따로 만들지 않는다)", () => {
  const rows = goalProcessRows(
    ["Anki.exe"],
    [usage("anki.exe", 30), usage("ANKI.EXE", 10), usage("other.exe", 99)],
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].process, "anki.exe");
  assert.equal(rows[0].active_seconds, 40);
  assert.equal(rows[0].total_seconds, 40);
});

test("대소문자만 다른 도메인도 같은 사이트로 보고 합친다", () => {
  const rows = goalSiteRows(
    ["Claude.AI"],
    [site("claude.ai", 20), site("CLAUDE.ai", 5)],
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].active_seconds, 25);
});

test("연결한 사이트의 대소문자만 다른 중복은 한 번만 담는다", () => {
  const grouped = domainsByBrowser([
    { browser: "chrome.exe", domain: "A.com" },
    { browser: "chrome.exe", domain: "a.com" },
  ]);
  assert.deepEqual([...grouped], [["chrome.exe", ["A.com"]]]);
});
