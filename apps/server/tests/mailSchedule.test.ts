import assert from "node:assert/strict";
import { test } from "node:test";

import {
  latestOccurrence,
  localParts,
  periodFor,
  weekdayOf,
  zonedToUtc,
} from "../src/mail/schedule.ts";

const SEOUL = "Asia/Seoul";
const at = (iso: string) => new Date(iso);
const sub = (over: Record<string, unknown>) => ({
  frequency: "daily" as const,
  weekday: null,
  day_of_month: null,
  send_time: "09:00",
  timezone: SEOUL,
  ...over,
});

test("요일 번호는 월=0 … 일=6이다", () => {
  assert.equal(weekdayOf("2026-11-23"), 0); // 월요일
  assert.equal(weekdayOf("2026-11-22"), 6); // 일요일
});

test("그 시간대의 날짜와 시각", () => {
  assert.deepEqual(localParts(at("2026-11-22T15:30:00Z"), SEOUL), {
    date: "2026-11-23",
    minutes: 30,
  });
  assert.deepEqual(localParts(at("2026-11-22T15:30:00Z"), "UTC"), {
    date: "2026-11-22",
    minutes: 15 * 60 + 30,
  });
});

test("벽시계 시각을 UTC로(서머타임이 있는 시간대도)", () => {
  assert.equal(
    zonedToUtc("2026-11-23", "09:00", SEOUL).toISOString(),
    "2026-11-23T00:00:00.000Z",
  );
  assert.equal(
    zonedToUtc("2026-07-01", "09:00", "America/New_York").toISOString(),
    "2026-07-01T13:00:00.000Z",
  );
  assert.equal(
    zonedToUtc("2026-12-01", "09:00", "America/New_York").toISOString(),
    "2026-12-01T14:00:00.000Z",
  );
});

test("매일: 보낼 시각이 지났으면 오늘, 아니면 어제. 구간은 그 전날 하루", () => {
  const after = latestOccurrence(sub({}), at("2026-11-23T00:05:00Z")); // 서울 09:05
  assert.equal(after.key, "2026-11-23");
  assert.equal(after.at.toISOString(), "2026-11-23T00:00:00.000Z");
  assert.deepEqual(after.period, { start: "2026-11-22", end: "2026-11-22" });

  const before = latestOccurrence(sub({}), at("2026-11-22T23:55:00Z")); // 서울 08:55
  assert.equal(before.key, "2026-11-22");
  assert.deepEqual(before.period, { start: "2026-11-21", end: "2026-11-21" });
});

test("매주: 그 요일의 가장 최근 발송, 구간은 보낼 날 이전의 월~일", () => {
  const monday = sub({ frequency: "weekly", weekday: 0 });
  const onTime = latestOccurrence(monday, at("2026-11-23T00:05:00Z")); // 월 09:05
  assert.equal(onTime.key, "2026-11-23");
  assert.deepEqual(onTime.period, { start: "2026-11-16", end: "2026-11-22" });

  const early = latestOccurrence(monday, at("2026-11-22T23:00:00Z")); // 월 08:00
  assert.equal(early.key, "2026-11-16");
  assert.deepEqual(early.period, { start: "2026-11-09", end: "2026-11-15" });

  const midweek = latestOccurrence(monday, at("2026-11-25T03:00:00Z")); // 수
  assert.equal(midweek.key, "2026-11-23");

  // 수요일에 보내도 구간은 지난 월~일이다
  assert.deepEqual(periodFor("weekly", "2026-11-25"), {
    start: "2026-11-16",
    end: "2026-11-22",
  });
});

test("매월: 그날의 가장 최근 발송, 구간은 지난달(해가 바뀌어도)", () => {
  const first = sub({ frequency: "monthly", day_of_month: 1 });
  const onTime = latestOccurrence(first, at("2026-12-01T00:05:00Z"));
  assert.equal(onTime.key, "2026-12-01");
  assert.deepEqual(onTime.period, { start: "2026-11-01", end: "2026-11-30" });

  const before = latestOccurrence(first, at("2026-11-30T03:00:00Z"));
  assert.equal(before.key, "2026-11-01");
  assert.deepEqual(before.period, { start: "2026-10-01", end: "2026-10-31" });

  const newYear = latestOccurrence(first, at("2027-01-01T00:05:00Z"));
  assert.deepEqual(newYear.period, { start: "2026-12-01", end: "2026-12-31" });

  const late = sub({ frequency: "monthly", day_of_month: 28 });
  assert.equal(
    latestOccurrence(late, at("2027-02-27T03:00:00Z")).key,
    "2027-01-28",
  );
  assert.deepEqual(periodFor("monthly", "2027-03-28"), {
    start: "2027-02-01",
    end: "2027-02-28",
  });
});

test("날짜 변경선 근처의 시간대도 그 시간대의 날짜로 계산한다", () => {
  const kiritimati = sub({ timezone: "Pacific/Kiritimati" }); // UTC+14
  const occurrence = latestOccurrence(kiritimati, at("2026-11-22T19:30:00Z")); // 현지 11-23 09:30
  assert.equal(occurrence.key, "2026-11-23");
  assert.equal(occurrence.at.toISOString(), "2026-11-22T19:00:00.000Z");
});
