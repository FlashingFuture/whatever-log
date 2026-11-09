import assert from "node:assert/strict";
import { test } from "node:test";

import {
  chipFor,
  everyText,
  pollIntervalMs,
  relativeTime,
  type StatusLike,
} from "../../src/lib/syncStatus.ts";

const NOW = new Date("2026-11-07T03:00:00.000Z");
const ago = (seconds: number) =>
  new Date(NOW.getTime() - seconds * 1000).toISOString();

function status(over: Partial<StatusLike> = {}): StatusLike {
  return {
    enabled: true,
    state: "ok",
    result: "ok",
    last_attempt_at: ago(10),
    last_success_at: ago(10),
    problems: 0,
    interval_seconds: 300,
    ...over,
  };
}

test("상대 시간: 방금 / 분 / 시간 / 일", () => {
  assert.equal(relativeTime(ago(5), NOW), "방금");
  assert.equal(relativeTime(ago(59), NOW), "방금");
  assert.equal(relativeTime(ago(60), NOW), "1분 전");
  assert.equal(relativeTime(ago(59 * 60), NOW), "59분 전");
  assert.equal(relativeTime(ago(3600), NOW), "1시간 전");
  assert.equal(relativeTime(ago(23 * 3600), NOW), "23시간 전");
  assert.equal(relativeTime(ago(24 * 3600), NOW), "1일 전");
  assert.equal(relativeTime(ago(3 * 24 * 3600), NOW), "3일 전");
});

test("상대 시간: 없거나 읽을 수 없거나 한참 미래인 시각은 null(1분 안쪽의 시계 차이는 방금)", () => {
  assert.equal(relativeTime(null, NOW), null);
  assert.equal(relativeTime("garbage", NOW), null);
  assert.equal(relativeTime(ago(-3600), NOW), null);
  assert.equal(relativeTime(ago(-30), NOW), "방금");
});

test("동기화를 켜지 않았으면 칩을 그리지 않는다", () => {
  assert.equal(chipFor(status({ enabled: false, state: "off" }), NOW), null);
  assert.equal(chipFor(status({ state: "off" }), NOW), null);
});

test("정상이면 마지막 성공 시각과 함께 좋은 톤이다", () => {
  const chip = chipFor(status({ last_success_at: ago(5 * 60) }), NOW);

  assert.deepEqual([chip?.label, chip?.tone], ["동기화됨 · 5분 전", "good"]);
});

test("올리지 못한 항목이 있으면 건수를 알리고 주의 톤이다", () => {
  const chip = chipFor(status({ problems: 2 }), NOW);

  assert.deepEqual(
    [chip?.label, chip?.tone],
    ["일부만 동기화됨 · 2건", "warn"],
  );
  assert.match(chip?.detail ?? "", /목표 동기화/);
});

test("성공한 적이 없는 정상(건너뛴 주기뿐)은 시각 없이 준비됨으로 보여 준다", () => {
  const chip = chipFor(
    status({ last_success_at: null, result: "signed_out" }),
    NOW,
  );

  assert.deepEqual([chip?.label, chip?.tone], ["동기화 준비됨", "good"]);
});

test("에이전트가 한 번도 안 돌았으면 실행하라고 안내한다", () => {
  const chip = chipFor(
    status({
      state: "waiting",
      result: null,
      last_attempt_at: null,
      last_success_at: null,
    }),
    NOW,
  );

  assert.deepEqual([chip?.label, chip?.tone], ["동기화 대기 중", "warn"]);
  assert.match(chip?.detail ?? "", /sync_agent/);
});

test("에이전트가 멈췄으면 마지막 성공 시각과 실행 방법을 알린다", () => {
  const chip = chipFor(
    status({ state: "stale", last_success_at: ago(2 * 3600) }),
    NOW,
  );

  assert.deepEqual(
    [chip?.label, chip?.tone],
    ["에이전트 멈춤 · 2시간 전", "warn"],
  );
  assert.match(chip?.detail ?? "", /반영되지 않고 있어요/);
  assert.match(chip?.detail ?? "", /sync_agent/);
  assert.equal(
    chipFor(status({ state: "stale", last_success_at: null }), NOW)?.label,
    "에이전트 멈춤",
  );
});

test("오류는 종류별로 사용자가 할 일을 알려 준다", () => {
  const detail = (result: string) =>
    chipFor(status({ state: "error", result }), NOW)?.detail ?? "";

  assert.match(detail("unreachable"), /인터넷 연결/);
  assert.match(detail("not_authorized"), /다시 로그인/);
  assert.match(detail("server_error"), /서버가 요청을 처리하지 못했어요/);
  assert.match(detail("internal"), /문제가 생겼어요/);
  assert.match(detail("signed_out"), /로그인 정보를 찾지 못해/);
  assert.match(detail("signed_out"), /반영되지 않았어요/);
  assert.match(detail("something_new"), /문제가 생겼어요/);
  assert.equal(
    chipFor(status({ state: "error", result: "unreachable" }), NOW)?.tone,
    "bad",
  );
});

test("칩의 글자에는 이름·프로세스 같은 내용이 없고 시각만 있다", () => {
  const chip = chipFor(status({ problems: 1 }), NOW);

  assert.doesNotMatch(`${chip?.label}${chip?.detail}`, /\.exe|@/);
});

test("상태를 다시 묻는 간격: 정상이면 30초, 문제가 있으면 15초, 꺼짐·모름은 60초", () => {
  assert.equal(pollIntervalMs(null), 60_000);
  assert.equal(pollIntervalMs(status({ state: "off" })), 60_000);
  assert.equal(pollIntervalMs(status({ state: "ok" })), 30_000);
  assert.equal(pollIntervalMs(status({ state: "error" })), 15_000);
  assert.equal(pollIntervalMs(status({ state: "stale" })), 15_000);
  assert.equal(pollIntervalMs(status({ state: "waiting" })), 15_000);
});

test("화면은 로그인되어 있는데 에이전트가 로그인 정보를 못 찾으면 낡은 '동기화됨'이 아니라 오류로 보여 준다", () => {
  const chip = chipFor(
    status({
      state: "error",
      result: "signed_out",
      last_success_at: ago(2 * 3600),
    }),
    NOW,
  );

  assert.deepEqual([chip?.label, chip?.tone], ["동기화 오류", "bad"]);
  assert.match(chip?.detail ?? "", /마지막으로 동기화된 때: 2시간 전/);
});

test("방금 로그인해 에이전트의 다음 주기를 기다리는 중이면 오류가 아니라 곧 동기화된다고 알린다", () => {
  const chip = chipFor(
    status({ state: "pending", result: "signed_out", last_success_at: null }),
    NOW,
  );

  assert.deepEqual([chip?.label, chip?.tone], ["곧 동기화돼요", "neutral"]);
  assert.match(chip?.detail ?? "", /아직 동기화되지 않았어요/);
  assert.match(chip?.detail ?? "", /5분마다/);
  assert.equal(pollIntervalMs(status({ state: "pending" })), 15_000); // 다음 주기가 끝나면 곧 바뀌어 보이게
});

test("로그인한 뒤에도 로그인 정보를 못 찾으면: 아직 안 됨 → 주기마다 다시 시도 → 계속되면 자격 증명·다시 로그인 순으로 알린다", () => {
  const detail =
    chipFor(status({ state: "error", result: "signed_out" }), NOW)?.detail ??
    "";

  const order = [
    "아직 동기화되지 않았어요",
    "5분마다 다시 시도해요",
    "자격 증명 관리자",
    "로그아웃한 뒤 다시 로그인",
  ].map((phrase) => detail.indexOf(phrase));
  assert.ok(
    order.every((index) => index >= 0),
    detail,
  );
  assert.deepEqual(
    order,
    [...order].sort((a, b) => a - b),
  );
});

test("주기 글자: 분·초, 모르면 주기마다", () => {
  assert.equal(everyText(300), "5분마다");
  assert.equal(everyText(30), "30초마다");
  assert.equal(everyText(null), "주기마다");
  assert.equal(everyText(0), "주기마다");
});
