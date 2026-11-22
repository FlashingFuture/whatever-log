import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addDays,
  describePeriod,
  formatDayText,
  isOnCarousel,
  parseDayText,
  periodStatus,
} from "../../src/lib/goalPeriod.ts";

const NONE = { start_date: null, end_date: null };
const PERIOD = { start_date: "2026-11-10", end_date: "2026-11-12" };
const NOW = new Date(2026, 10, 11);

test("기간이 없으면 none, 있으면 시작 전·진행 중·종료됨이다(양끝 날짜도 진행 중)", () => {
  assert.equal(periodStatus(NONE, "2026-11-11"), "none");
  assert.equal(periodStatus(PERIOD, "2026-11-09"), "upcoming");
  assert.equal(periodStatus(PERIOD, "2026-11-10"), "active");
  assert.equal(periodStatus(PERIOD, "2026-11-12"), "active");
  assert.equal(periodStatus(PERIOD, "2026-11-13"), "ended");
});

test("기간이 한쪽만 있으면(서버가 거르는 값) 기간 없음으로 본다", () => {
  assert.equal(
    periodStatus({ start_date: "2026-11-10", end_date: null }, "2026-11-11"),
    "none",
  );
});

test("홈 캐러셀에는 종료된 목표만 빠진다", () => {
  assert.equal(isOnCarousel(NONE, "2026-12-01"), true);
  assert.equal(isOnCarousel(PERIOD, "2026-11-09"), true); // 곧 시작할 목표는 둔다
  assert.equal(isOnCarousel(PERIOD, "2026-11-11"), true);
  assert.equal(isOnCarousel(PERIOD, "2026-11-13"), false);
});

test("날짜 글자는 올해면 월·일만, 다른 해면 연도까지 보인다", () => {
  assert.equal(formatDayText("2026-11-05", NOW), "11월 5일");
  assert.equal(formatDayText("2027-01-03", NOW), "2027년 1월 3일");
  assert.equal(formatDayText("내일", NOW), "내일");
});

test("기간 설명은 상태를 붙인다", () => {
  assert.equal(describePeriod(NONE, "2026-11-11", NOW), "기간 없음");
  assert.equal(
    describePeriod(PERIOD, "2026-11-11", NOW),
    "11월 10일 ~ 11월 12일",
  );
  assert.equal(
    describePeriod(PERIOD, "2026-11-09", NOW),
    "11월 10일 ~ 11월 12일 · 시작 전",
  );
  assert.equal(
    describePeriod(PERIOD, "2026-11-13", NOW),
    "11월 10일 ~ 11월 12일 · 종료됨",
  );
});

test("날짜 글자 해석은 엄격하고 없는 날짜는 거부한다", () => {
  assert.equal(parseDayText("2026-02-28")?.getDate(), 28);
  for (const text of [
    "2026-02-30",
    "2026-13-01",
    "2026-1-5",
    "20261105",
    "",
    "abc",
  ]) {
    assert.equal(parseDayText(text), null, text);
  }
});

test("날짜에 일 수를 더한다(달·해를 넘어도 맞다)", () => {
  assert.equal(addDays("2026-11-05", 30), "2026-12-05");
  assert.equal(addDays("2026-12-31", 1), "2027-01-01");
  assert.equal(addDays("2026-03-01", -1), "2026-02-28");
  assert.equal(addDays("bad", 1), null);
});
