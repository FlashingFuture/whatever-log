import assert from "node:assert/strict";
import { test } from "node:test";

import {
  achievement,
  dayRange,
  goalTotalSeconds,
  localDay,
  resolveSelection,
  settleSelection,
  timePair,
} from "../../src/lib/goalSelection.ts";

const GOALS = [
  { id: 1, name: "공부", active_seconds: 3600 },
  { id: 2, name: "운동", active_seconds: 1200 },
];

// --- 날짜 범위 ---

test("로컬 날짜는 UTC로 바꾸지 않고 달력 날짜 그대로 쓴다", () => {
  assert.equal(localDay(new Date(2026, 10, 9, 0, 30)), "2026-11-09"); // 자정 직후 — UTC로 바꾸면 전날이 될 수 있다
  assert.equal(localDay(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
});

test("구간의 끝(미포함)은 하루 전이 마지막 날이다", () => {
  assert.deepEqual(dayRange(new Date(2026, 10, 9), new Date(2026, 10, 10)), {
    from: "2026-11-09",
    to: "2026-11-09",
  }); // 일
  assert.deepEqual(dayRange(new Date(2026, 10, 9), new Date(2026, 10, 16)), {
    from: "2026-11-09",
    to: "2026-11-15",
  }); // 주
  assert.deepEqual(dayRange(new Date(2026, 10, 1), new Date(2026, 11, 1)), {
    from: "2026-11-01",
    to: "2026-11-30",
  }); // 월
});

test("월·연이 바뀌는 구간의 마지막 날을 바르게 구한다", () => {
  assert.deepEqual(dayRange(new Date(2026, 11, 1), new Date(2027, 0, 1)), {
    from: "2026-12-01",
    to: "2026-12-31",
  });
  assert.deepEqual(dayRange(new Date(2026, 1, 1), new Date(2026, 2, 1)), {
    from: "2026-02-01",
    to: "2026-02-28",
  });
});

test("끝이 시작보다 앞서면 시작 하루로 본다", () => {
  assert.deepEqual(dayRange(new Date(2026, 10, 9), new Date(2026, 10, 9)), {
    from: "2026-11-09",
    to: "2026-11-09",
  });
});

// --- 선택 ---

test("고른 목표가 목록에 없으면(지웠다) 목표 전체로 돌아간다", () => {
  assert.equal(resolveSelection(2, GOALS), 2);
  assert.equal(resolveSelection(9, GOALS), null);
  assert.equal(resolveSelection(null, GOALS), null);
  assert.equal(resolveSelection(1, []), null);
});

// --- 전체 시간 ---

test("서버 합계가 이 PC의 실시간 값보다 늦으면 전체가 현 기기보다 작아 보이지 않게 큰 쪽을 쓴다", () => {
  assert.equal(goalTotalSeconds(4530, 75), 4530); // 서버는 75분, 이 PC는 75분 30초
  assert.equal(goalTotalSeconds(600, 75), 4500); // 다른 기기가 더 했다
  assert.equal(goalTotalSeconds(600, undefined), 600); // 서버에 연결되지 않은 목표
  assert.equal(goalTotalSeconds(0, 0), 0);
});

test("목표 전체: 모든 목표를 목표별로 따져 더한다", () => {
  const pair = timePair(GOALS, null, {
    state: "synced",
    goals: [
      { id: 1, minutes: 100 }, // 6000초 > 이 PC 3600초
      { id: 2, minutes: 5 }, // 300초 < 이 PC 1200초
    ],
  });

  assert.deepEqual(pair, { total: 6000 + 1200, device: 4800 });
});

test("목표 하나를 고르면 그 목표만 센다", () => {
  const totals = {
    state: "synced" as const,
    goals: [
      { id: 1, minutes: 100 },
      { id: 2, minutes: 30 },
    ],
  };

  assert.deepEqual(timePair(GOALS, 2, totals), { total: 1800, device: 1200 });
  assert.deepEqual(timePair(GOALS, 1, totals), { total: 6000, device: 3600 });
});

test("서버에 연결되지 않은 목표는 합계 목록에 없어도 이 PC의 값을 전체에 더한다", () => {
  const pair = timePair(GOALS, null, {
    state: "synced",
    goals: [{ id: 1, minutes: 100 }], // 2번 목표는 로컬에만 있다
  });

  assert.deepEqual(pair, { total: 6000 + 1200, device: 4800 });
});

test("다른 기기의 기록을 받을 수 없는 상태(local)면 이 PC의 값이 전체다", () => {
  assert.deepEqual(timePair(GOALS, null, { state: "local", goals: [] }), {
    total: 4800,
    device: 4800,
  });
});

test("합계를 받지 못했으면(unavailable·요청 실패) 전체는 모르고 현 기기만 보인다", () => {
  assert.deepEqual(timePair(GOALS, null, { state: "unavailable", goals: [] }), {
    total: null,
    device: 4800,
  });
  assert.deepEqual(timePair(GOALS, 1, null), { total: null, device: 3600 });
});

test("목표가 없으면 0이다", () => {
  assert.deepEqual(timePair([], null, { state: "local", goals: [] }), {
    total: 0,
    device: 0,
  });
  assert.deepEqual(timePair([], null, null), { total: null, device: 0 });
});

test("없는 목표를 고른 채 부르면 0이다(호출부가 resolveSelection으로 먼저 정리한다)", () => {
  assert.deepEqual(timePair(GOALS, 9, { state: "local", goals: [] }), {
    total: 0,
    device: 0,
  });
});

// --- 달성률 ---

const WITH_TARGETS = [
  { id: 1, name: "공부", active_seconds: 3600, target_minutes: 120 },
  { id: 2, name: "운동", active_seconds: 1200, target_minutes: 60 },
  { id: 3, name: "쉬는 목표", active_seconds: 5000, target_minutes: 0 }, // 이 구간에는 적용하는 날이 없다
];

test("목표 하나의 달성률은 수행 시간 ÷ 구간의 목표량이다", () => {
  const rate = achievement(WITH_TARGETS, 1, { state: "local", goals: [] });

  assert.deepEqual(rate, {
    percent: 50, // 3600초 ÷ (120분 = 7200초)
    achievedSeconds: 3600,
    targetSeconds: 7200,
    basis: "total",
  });
});

test("목표 전체의 달성률은 목표량이 있는 목표만 분자·분모에 넣는다", () => {
  const rate = achievement(WITH_TARGETS, null, { state: "local", goals: [] });

  // (3600 + 1200) ÷ ((120 + 60)분) — 목표량이 0인 목표의 5000초는 다른 목표의 부족을 메우지 않는다
  assert.equal(rate?.achievedSeconds, 4800);
  assert.equal(rate?.targetSeconds, 10800);
  assert.equal(rate?.percent, 44);
});

test("분자는 모든 기기의 합이다(서버 합계가 이 PC보다 크면 그 값)", () => {
  const rate = achievement(WITH_TARGETS, 1, {
    state: "synced",
    goals: [{ id: 1, minutes: 100 }], // 6000초
  });

  assert.equal(rate?.achievedSeconds, 6000);
  assert.equal(rate?.percent, 83);
  assert.equal(rate?.basis, "total");
});

test("전체를 알 수 없으면 현 기기 시간으로 계산하고 그렇다고 알린다", () => {
  for (const totals of [null, { state: "unavailable" as const, goals: [] }]) {
    const rate = achievement(WITH_TARGETS, 1, totals);

    assert.equal(rate?.basis, "device");
    assert.equal(rate?.percent, 50);
  }
});

test("100%를 넘을 수 있다", () => {
  const rate = achievement(
    [{ id: 1, name: "공부", active_seconds: 9000, target_minutes: 60 }],
    1,
    { state: "local", goals: [] },
  );

  assert.equal(rate?.percent, 250);
});

test("목표를 적용하는 날이 없는 구간이면 달성률이 없다", () => {
  assert.equal(achievement(WITH_TARGETS, 3, null), null); // 목표량 0인 목표 하나
  assert.equal(
    achievement(
      [{ id: 3, name: "쉼", active_seconds: 5000, target_minutes: 0 }],
      null,
      null,
    ),
    null,
  );
  assert.equal(achievement([], null, null), null);
});

test("목표량을 모르면(없는 값) 달성률을 만들지 않는다", () => {
  assert.equal(
    achievement([{ id: 1, name: "공부", active_seconds: 100 }], null, null),
    null,
  );
});

test("수행이 없으면 0%다(목표량이 있다)", () => {
  const rate = achievement(
    [{ id: 1, name: "공부", active_seconds: 0, target_minutes: 60 }],
    1,
    { state: "local", goals: [] },
  );

  assert.equal(rate?.percent, 0);
});

test("퍼센트는 반올림한다(0.5는 올림)", () => {
  const rate = (seconds: number) =>
    achievement(
      [{ id: 1, name: "공부", active_seconds: seconds, target_minutes: 200 }],
      1,
      { state: "local", goals: [] },
    )?.percent;

  assert.equal(rate(60), 1); // 0.5% → 1
  assert.equal(rate(59), 0); // 0.49% → 0
});

// --- 목표 진행 조회가 실패한 갱신 ---

test("목표 진행 조회가 실패한 갱신(null)은 고른 목표를 그대로 둔다", () => {
  assert.equal(settleSelection(2, null), 2);
  assert.equal(settleSelection(null, null), null);
});

test("목록을 받았다면 지운 목표만 목표 전체로 돌아간다", () => {
  assert.equal(settleSelection(2, GOALS), 2);
  assert.equal(settleSelection(9, GOALS), null);
  assert.equal(settleSelection(2, []), null); // 성공했는데 목표가 하나도 없다 — 지운 것이다
});

test("실패한 갱신 뒤 성공한 갱신에서 고른 목표가 살아 있다", () => {
  let selected: number | null = 2;
  selected = settleSelection(selected, null); // 15초 갱신 한 번 실패
  selected = settleSelection(selected, GOALS); // 다음 갱신 성공

  assert.equal(selected, 2);
});
