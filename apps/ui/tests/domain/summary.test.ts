import assert from "node:assert/strict";
import { test } from "node:test";

import type { ProcessUsage } from "../../src/api/index.ts";
import { summarizeUsage } from "../../src/domain/summary.ts";

function usage(process: string, active: number, idle = 0): ProcessUsage {
  return {
    process,
    active_seconds: active,
    idle_seconds: idle,
    background_seconds: 1000,
    total_seconds: active + idle + 1000,
  };
}

test("총 사용 시간은 집중 시간의 합이고, 가장 많이 쓴 프로그램은 집중 시간이 가장 긴 것", () => {
  const summary = summarizeUsage([
    usage("a.exe", 60, 5),
    usage("b.exe", 300, 10),
    usage("c.exe", 120),
  ]);

  assert.equal(summary.activeSeconds, 480);
  assert.equal(summary.idleSeconds, 15);
  assert.equal(summary.top?.process, "b.exe");
});

test("동률이면 앞선 프로세스를 고른다", () => {
  const summary = summarizeUsage([usage("a.exe", 60), usage("b.exe", 60)]);

  assert.equal(summary.top?.process, "a.exe");
});

test("집중 시간이 없으면 가장 많이 쓴 프로그램은 없다", () => {
  assert.equal(summarizeUsage([usage("a.exe", 0, 30)]).top, null);
  assert.equal(summarizeUsage([]).top, null);
  assert.equal(summarizeUsage([]).activeSeconds, 0);
});
