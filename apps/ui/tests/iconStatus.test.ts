import assert from "node:assert/strict";
import { test } from "node:test";

import {
  IconStatusCache,
  MISSING_TTL_MS,
  TRANSIENT_TTL_MS,
} from "../src/iconStatus.ts";

test("없음은 5분, 일시적 실패는 30초 동안만 기억한다", () => {
  const cache = new IconStatusCache();
  cache.record("a.exe", "missing", 0);
  cache.record("b.exe", "transient", 0);

  assert.equal(cache.statusOf("a.exe", MISSING_TTL_MS - 1), "missing");
  assert.equal(cache.statusOf("a.exe", MISSING_TTL_MS), null);
  assert.equal(cache.statusOf("b.exe", TRANSIENT_TTL_MS - 1), "transient");
  assert.equal(cache.statusOf("b.exe", TRANSIENT_TTL_MS), null);
  assert.equal(cache.statusOf("never.exe", 0), null);
});

test("새로 기록할 때 만료된 항목을 함께 지워 쌓이지 않는다", () => {
  const cache = new IconStatusCache();
  for (let i = 0; i < 50; i++) {
    cache.record(`old${i}.exe`, "missing", 0); // 한 번만 요청되고 다시 안 물어보는 이름들
  }
  assert.equal(cache.size, 50);

  cache.record("new.exe", "missing", MISSING_TTL_MS + 1);

  assert.equal(cache.size, 1);
  assert.equal(cache.statusOf("new.exe", MISSING_TTL_MS + 2), "missing");
});

test("같은 이름을 다시 기록하면 상태와 시각이 갱신된다(일시적 → 없음)", () => {
  const cache = new IconStatusCache();
  cache.record("a.exe", "transient", 0);
  cache.record("a.exe", "missing", 10_000);

  assert.equal(cache.statusOf("a.exe", 10_000 + TRANSIENT_TTL_MS), "missing");
});
