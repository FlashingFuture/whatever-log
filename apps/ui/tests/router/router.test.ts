import assert from "node:assert/strict";
import { test } from "node:test";

import {
  HOME,
  isSameRoute,
  parseRoute,
  routeHref,
} from "../../src/router/router.ts";

test("홈은 #/ 이고 모르는 주소도 홈으로 본다", () => {
  assert.equal(routeHref(HOME), "#/");
  assert.deepEqual(parseRoute(""), HOME);
  assert.deepEqual(parseRoute("#/"), HOME);
  assert.deepEqual(parseRoute("#/nowhere"), HOME);
});

test("프로세스 주소는 이름을 인코딩해서 왕복한다(공백·점·슬래시·한글)", () => {
  for (const process of [
    "chrome.exe",
    "Docker Desktop.exe",
    "a/b.exe",
    "메모장.exe",
  ]) {
    const route = { name: "process", process } as const;
    assert.deepEqual(parseRoute(routeHref(route)), route);
  }
  assert.equal(
    routeHref({ name: "process", process: "Docker Desktop.exe" }),
    "#/process/Docker%20Desktop.exe",
  );
});

test("깨진 인코딩이나 빈 이름은 홈으로", () => {
  assert.deepEqual(parseRoute("#/process/%E0%A4%A"), HOME);
  assert.deepEqual(parseRoute("#/process/"), HOME);
});

test("같은 경로 판정", () => {
  assert.equal(isSameRoute(HOME, parseRoute("")), true);
  assert.equal(
    isSameRoute(
      { name: "process", process: "a" },
      { name: "process", process: "b" },
    ),
    false,
  );
});

test("복원 중에는 이동해도 기록의 스크롤 위치를 덮어쓰지 않는다", async () => {
  const globals = globalThis as Record<string, unknown>;
  const { restoreScroll } = await import("../../src/router/scroll.ts");
  const { navigate } = await import("../../src/router/router.ts");

  const history = {
    state: { depth: 0, scrollY: 500 } as object | null,
    replaced: 0,
    savedY: undefined as number | undefined,
    replaceState(state: object) {
      this.replaced += 1;
      this.savedY = (state as { scrollY?: number }).scrollY;
      this.state = state;
    },
    pushState(state: object) {
      this.state = state;
    },
  };
  const fakeWindow = {
    scrollY: 150, // 짧은 문서에서 밀린 중간값
    location: { hash: "#/" },
    history,
    scrollTo() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {},
  };
  globals.window = fakeWindow;
  globals.document = { documentElement: {} };
  globals.ResizeObserver = class {
    observe(): void {}
    disconnect(): void {}
  };
  try {
    const stop = restoreScroll(500);
    navigate({ name: "process", process: "a.exe" });
    assert.equal(history.replaced, 0, "중간값을 기록에 적지 않는다");
    assert.equal((history.state as { depth: number }).depth, 1, "이동은 한다");

    stop(); // 복원이 끝난 뒤의 이동은 지금 위치를 적는다
    fakeWindow.location.hash = "#/process/a.exe";
    navigate({ name: "home" });
    assert.equal(history.replaced, 1);
    assert.equal(history.savedY, 150, "지금 위치(150)를 적는다");
  } finally {
    delete globals.window;
    delete globals.document;
    delete globals.ResizeObserver;
  }
});
