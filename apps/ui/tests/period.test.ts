// Node 내장 테스트 러너로 돈다(`pnpm --filter ui test`) — 순수 함수라 브라우저나
// 테스트 라이브러리 없이 확인할 수 있다. 경계가 로컬 타임존 기준이라 TZ를
// 테스트마다 고정한다(Node는 process.env.TZ를 바꾸면 바로 반영한다).
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  anchorForUnitChange,
  formatPeriod,
  isCurrentPeriod,
  periodContaining,
  shiftPeriod,
} from "../src/period.ts";

const originalTz = process.env.TZ;

function useTimezone(tz: string): void {
  process.env.TZ = tz;
}

afterEach(() => {
  process.env.TZ = originalTz;
});

const HOUR_MS = 60 * 60 * 1000;

test("day: 로컬 자정부터 다음 자정까지", () => {
  useTimezone("Asia/Seoul");
  const period = periodContaining("day", new Date(2026, 9, 29, 14, 30));

  assert.deepEqual(period.start, new Date(2026, 9, 29));
  assert.deepEqual(period.end, new Date(2026, 9, 30));
  // KST 자정은 UTC 전날 15시다 — UTC 0시 기준과 다르다는 걸 고정해둔다.
  assert.equal(period.start.toISOString(), "2026-10-28T15:00:00.000Z");
});

test("week: 일요일이면 그 전 월요일부터 시작한다", () => {
  useTimezone("Asia/Seoul");
  const sunday = new Date(2026, 10, 1, 12); // 2026-11-01은 일요일
  const period = periodContaining("week", sunday);

  assert.deepEqual(period.start, new Date(2026, 9, 26)); // 월요일
  assert.deepEqual(period.end, new Date(2026, 10, 2)); // 다음 월요일
});

test("week: 월요일이면 그날부터 시작한다", () => {
  useTimezone("Asia/Seoul");
  const period = periodContaining("week", new Date(2026, 9, 26, 0, 0));

  assert.deepEqual(period.start, new Date(2026, 9, 26));
});

test("month: 1일부터 다음 달 1일까지, 연도를 넘어가도 이어진다", () => {
  useTimezone("Asia/Seoul");
  const december = periodContaining("month", new Date(2026, 11, 31, 23));

  assert.deepEqual(december.start, new Date(2026, 11, 1));
  assert.deepEqual(december.end, new Date(2027, 0, 1));
  assert.deepEqual(shiftPeriod(december, 1).start, new Date(2027, 0, 1));
  assert.deepEqual(shiftPeriod(december, -1).start, new Date(2026, 10, 1));
});

test("day: 월말에서 하루 뒤로 가면 다음 달 1일이 된다", () => {
  useTimezone("Asia/Seoul");
  const period = periodContaining("day", new Date(2026, 9, 31));

  assert.deepEqual(shiftPeriod(period, 1).start, new Date(2026, 10, 1));
});

test("일광절약시간 전환일은 23시간/25시간짜리 하루가 된다", () => {
  // 2026-03-08 미국 동부 서머타임 시작(02시→03시), 2026-11-01 종료(02시→01시).
  useTimezone("America/New_York");
  const springForward = periodContaining("day", new Date(2026, 2, 8, 12));
  const fallBack = periodContaining("day", new Date(2026, 10, 1, 12));

  assert.equal(
    springForward.end.getTime() - springForward.start.getTime(),
    23 * HOUR_MS,
  );
  assert.equal(fallBack.end.getTime() - fallBack.start.getTime(), 25 * HOUR_MS);
  // 경계는 여전히 로컬 자정이어야 한다.
  assert.equal(springForward.end.getHours(), 0);
  assert.equal(fallBack.end.getHours(), 0);
});

test("현재 구간 판정: 끝 시각은 포함하지 않는다", () => {
  useTimezone("Asia/Seoul");
  const period = periodContaining("day", new Date(2026, 9, 29));

  assert.equal(isCurrentPeriod(period, new Date(2026, 9, 29, 23, 59)), true);
  assert.equal(isCurrentPeriod(period, new Date(2026, 9, 30, 0, 0)), false);
  assert.equal(isCurrentPeriod(period, new Date(2026, 9, 28, 23, 59)), false);
});

test("단위를 바꿀 때 현재 구간이면 지금을, 지난 구간이면 그 시작을 기준으로 한다", () => {
  useTimezone("Asia/Seoul");
  const now = new Date(2026, 9, 29, 14);
  const thisMonth = periodContaining("month", now);
  const lastMonth = shiftPeriod(thisMonth, -1);

  // 이번 달에서 "일"로 바꾸면 1일이 아니라 오늘로 가야 한다.
  assert.deepEqual(
    periodContaining("day", anchorForUnitChange(thisMonth, now)).start,
    new Date(2026, 9, 29),
  );
  assert.deepEqual(
    periodContaining("day", anchorForUnitChange(lastMonth, now)).start,
    new Date(2026, 8, 1),
  );
});

test("라벨 형식", () => {
  useTimezone("Asia/Seoul");
  assert.equal(
    formatPeriod(periodContaining("day", new Date(2026, 9, 29))),
    "2026년 10월 29일 (목)",
  );
  assert.equal(
    formatPeriod(periodContaining("month", new Date(2026, 9, 29))),
    "2026년 10월",
  );
  assert.equal(
    formatPeriod(periodContaining("week", new Date(2026, 9, 29))),
    "2026.10.26 – 11.01",
  );
  // 연도를 넘어가는 주는 끝 날짜에도 연도를 붙인다.
  assert.equal(
    formatPeriod(periodContaining("week", new Date(2026, 11, 30))),
    "2026.12.28 – 2027.01.03",
  );
});
