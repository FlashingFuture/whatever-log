import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canChooseDaily,
  describeSubscription,
  endedReasonText,
  initialFields,
  type SubscriptionLike,
  savedText,
  sectionKind,
} from "../../src/lib/mailSubscription.ts";

function sub(over: Partial<SubscriptionLike> = {}): SubscriptionLike {
  return {
    goal_id: 1,
    goal_name: "공부",
    frequency: "weekly",
    weekday: 0,
    day_of_month: null,
    send_time: "09:00",
    timezone: "Asia/Seoul",
    status: "active",
    ended_reason: null,
    ...over,
  };
}

test("이 목표의 구독이면 mine, 다른 목표의 살아 있는 구독이면 other, 없거나 다른 목표의 구독이 끝났으면 none", () => {
  assert.equal(sectionKind(null, 1), "none");
  assert.equal(sectionKind(sub(), 1), "mine");
  assert.equal(
    sectionKind(sub({ status: "ended", ended_reason: "goal_deleted" }), 1),
    "mine",
  );
  assert.equal(sectionKind(sub({ goal_id: 2 }), 1), "other");
  assert.equal(sectionKind(sub({ goal_id: null }), 1), "other"); // 다른 PC에서 신청한 목표
  assert.equal(sectionKind(sub({ goal_id: 2, status: "paused" }), 1), "other");
  assert.equal(sectionKind(sub({ goal_id: 2, status: "ended" }), 1), "none");
});

test("구독 한 줄은 일정과 상태, 시간대가 이 PC와 다를 때만 시간대를 붙인다", () => {
  assert.equal(
    describeSubscription(sub(), "Asia/Seoul"),
    "매주 월요일 09:00 · 켜짐",
  );
  assert.equal(
    describeSubscription(
      sub({ status: "paused", timezone: "UTC" }),
      "Asia/Seoul",
    ),
    "매주 월요일 09:00 (UTC) · 꺼짐",
  );
  assert.equal(
    describeSubscription(
      sub({
        frequency: "monthly",
        weekday: null,
        day_of_month: 1,
        status: "ended",
      }),
      "Asia/Seoul",
    ),
    "매달 1일 09:00 · 끝남",
  );
});

test("끝난 이유는 사람이 읽는 문장으로, 모르는 이유는 일반 문장으로", () => {
  assert.match(endedReasonText("goal_ended"), /마지막 보고서/);
  assert.match(endedReasonText("suppressed"), /반송/);
  assert.equal(endedReasonText("something_new"), "보고서 구독이 끝났어요.");
  assert.equal(endedReasonText(null), "보고서 구독이 끝났어요.");
});

test("신청 결과 문장은 확인 메일 결과를 알린다", () => {
  assert.equal(
    savedText(true, "sent"),
    "보고서 메일을 신청했어요. 확인 메일을 보냈어요.",
  );
  assert.equal(savedText(false, "already"), "보고서 메일 일정을 바꿨어요.");
  assert.match(savedText(true, "failed"), /확인 메일은 지금 보내지 못했어요/);
  assert.match(savedText(true, "suppressed"), /보내지 않았어요/);
});

test("폼의 처음 값: 이 목표의 구독 → 옛 로컬 일정 → 기본", () => {
  const legacy = {
    frequency: "monthly",
    weekday: null,
    day_of_month: 15,
    send_time: "21:00",
  };
  assert.deepEqual(initialFields(sub({ send_time: "07:30" }), legacy), {
    frequency: "weekly",
    weekday: 0,
    day_of_month: null,
    send_time: "07:30",
  });
  assert.deepEqual(initialFields(null, legacy), legacy);
  assert.deepEqual(initialFields(null, null), {
    frequency: "weekly",
    weekday: 0,
    day_of_month: null,
    send_time: "09:00",
  });
  assert.equal(
    initialFields(null, { ...legacy, frequency: "hourly" }).frequency,
    "weekly",
  );
});

test("매일은 상한이 남았거나 이미 이 목표를 매일 받을 때만 고를 수 있다", () => {
  assert.equal(canChooseDaily(true, null), true);
  assert.equal(canChooseDaily(false, null), false);
  assert.equal(
    canChooseDaily(false, sub({ frequency: "daily", weekday: null })),
    true,
  );
  assert.equal(
    canChooseDaily(
      false,
      sub({ frequency: "daily", weekday: null, status: "paused" }),
    ),
    false,
  );
});
