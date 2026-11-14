import assert from "node:assert/strict";
import { test } from "node:test";

import {
  describeAlert,
  describeSchedule,
  integerValue,
} from "../../src/lib/goalSettings.ts";

const ALERT = {
  target_process: null,
  deadline: "23:00",
  min_minutes: 30,
  weekdays: [0, 1, 2, 3, 4, 5, 6],
  enabled: true,
};

test("알림 규칙은 마감·대상·시간·요일을 한 줄로 보인다", () => {
  assert.equal(describeAlert(ALERT), "23:00까지 · 목표 전체 30분 · 매일");
  assert.equal(
    describeAlert({
      ...ALERT,
      target_process: "Arknights.exe",
      min_minutes: 1,
      weekdays: [0, 1, 2, 3, 4],
    }),
    "23:00까지 · Arknights.exe 1분 · 평일",
  );
});

const SCHEDULE = {
  enabled: true,
  frequency: "daily",
  weekday: null,
  day_of_month: null,
  send_time: "21:30",
};

test("보고서 일정은 주기에 맞는 말로 보인다", () => {
  assert.equal(describeSchedule(SCHEDULE), "매일 21:30");
  assert.equal(
    describeSchedule({ ...SCHEDULE, frequency: "weekly", weekday: 0 }),
    "매주 월요일 21:30",
  );
  assert.equal(
    describeSchedule({ ...SCHEDULE, frequency: "weekly", weekday: 6 }),
    "매주 일요일 21:30",
  );
  assert.equal(
    describeSchedule({ ...SCHEDULE, frequency: "monthly", day_of_month: 15 }),
    "매달 15일 21:30",
  );
});

test("모르는 주기나 빠진 값도 깨지지 않는다", () => {
  assert.equal(
    describeSchedule({ ...SCHEDULE, frequency: "yearly" }),
    "yearly 21:30",
  );
  assert.equal(
    describeSchedule({ ...SCHEDULE, frequency: "weekly", weekday: null }),
    "매주 ?요일 21:30",
  );
  assert.equal(
    describeSchedule({ ...SCHEDULE, frequency: "weekly", weekday: 9 }),
    "매주 ?요일 21:30",
  );
});

test("분 칸은 10진 정수 글자만 숫자로 바꾸고 나머지는 그대로 서버에 보낸다", () => {
  assert.equal(integerValue("30"), 30);
  assert.equal(integerValue("0"), 0);
  for (const text of [
    "",
    " 5",
    "5 ",
    "05",
    "1e2",
    "0x10",
    "-1",
    "1.5",
    "abc",
  ]) {
    assert.equal(integerValue(text), text, text);
  }
});
