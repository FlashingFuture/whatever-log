import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bannerText,
  footerText,
  shouldShowBanner,
  type UpdateLike,
} from "../../src/lib/updateNotice.ts";

function state(over: Partial<UpdateLike> = {}): UpdateLike {
  return {
    supported: true,
    enabled: true,
    current: "1.0.0-beta.2",
    latest: { version: "1.0.0" },
    available: true,
    error: null,
    ...over,
  };
}

test("새 버전이 있고 켜져 있으면 알리고, 그 버전을 넘겼으면 다음 버전까지 알리지 않는다", () => {
  assert.equal(shouldShowBanner(state(), null), true);
  assert.equal(shouldShowBanner(state(), "1.0.0"), false);
  assert.equal(
    shouldShowBanner(state({ latest: { version: "1.0.1" } }), "1.0.0"),
    true,
  );
});

test("꺼졌거나, 개발 모양이거나, 새 버전이 없거나, 상태를 모르면 알리지 않는다", () => {
  assert.equal(shouldShowBanner(null, null), false);
  assert.equal(shouldShowBanner(state({ enabled: false }), null), false);
  assert.equal(shouldShowBanner(state({ supported: false }), null), false);
  assert.equal(
    shouldShowBanner(state({ available: false, latest: null }), null),
    false,
  );
});

test("알림 문장과 아래 줄", () => {
  assert.equal(
    bannerText(state()),
    "새 버전 v1.0.0이 나왔어요 (지금 v1.0.0-beta.2)",
  );
  assert.equal(
    footerText(state()),
    "whatever.log 1.0.0-beta.2 · 새 버전 v1.0.0",
  );
  assert.equal(
    footerText(state({ available: false, latest: null })),
    "whatever.log 1.0.0-beta.2 · 최신 버전",
  );
  assert.equal(
    footerText(state({ enabled: false })),
    "whatever.log 1.0.0-beta.2 · 새 버전 알림 꺼짐",
  );
  assert.equal(
    footerText(state({ supported: false, current: "1.0.0-beta.2 (개발)" })),
    "whatever.log 1.0.0-beta.2 (개발)",
  );
  assert.match(
    footerText(
      state({
        available: false,
        latest: null,
        error: "새 버전을 확인하지 못했어요(URLError).",
      }),
    ),
    /확인하지 못했어요/,
  );
});
