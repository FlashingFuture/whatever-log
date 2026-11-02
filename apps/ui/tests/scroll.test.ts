import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";

import {
  isScrollbarPress,
  isScrollKey,
  MAX_RESTORE_MS,
  restoreScroll,
  stopsRestore,
  trackScroll,
} from "../src/scroll.ts";

test("페이지를 스크롤하는 키만 복원을 멈춘다", () => {
  for (const key of [
    "ArrowUp",
    "ArrowDown",
    "PageUp",
    "PageDown",
    "Home",
    "End",
    " ",
  ]) {
    assert.equal(isScrollKey(key), true, key);
  }
  for (const key of [
    "Tab",
    "Enter",
    "Escape",
    "a",
    "Shift",
    "ArrowLeft",
    "ArrowRight",
  ]) {
    assert.equal(isScrollKey(key), false, key);
  }
});

test("스크롤 키라도 피커가 막은 입력(defaultPrevented)은 멈추지 않는다", () => {
  assert.equal(
    stopsRestore({ key: "ArrowDown", defaultPrevented: false }),
    true,
  );
  assert.equal(
    stopsRestore({ key: "ArrowDown", defaultPrevented: true }),
    false,
  );
  assert.equal(stopsRestore({ key: "Tab", defaultPrevented: false }), false);
});

test("버튼·입력창 위의 Space는 스크롤이 아니라 누르기라 멈추지 않는다", () => {
  assert.equal(
    stopsRestore({ key: " ", defaultPrevented: false, targetTag: "BUTTON" }),
    false,
  );
  assert.equal(
    stopsRestore({ key: " ", defaultPrevented: false, targetTag: "INPUT" }),
    false,
  );
  assert.equal(
    stopsRestore({ key: " ", defaultPrevented: false, targetTag: "BODY" }),
    true,
  );
  // 방향키는 버튼에 포커스가 있어도 페이지를 스크롤한다.
  assert.equal(
    stopsRestore({
      key: "ArrowDown",
      defaultPrevented: false,
      targetTag: "BUTTON",
    }),
    true,
  );
});

test("스크롤 막대를 잡은 포인터만 복원을 멈춘다(내용 위의 일반 클릭은 무시)", () => {
  const root = { clientWidth: 1000, clientHeight: 700 };

  assert.equal(
    isScrollbarPress({ target: root, clientX: 1008, clientY: 100 }, root),
    true,
  ); // 세로 막대
  assert.equal(
    isScrollbarPress({ target: root, clientX: 100, clientY: 710 }, root),
    true,
  ); // 가로 막대
  assert.equal(
    isScrollbarPress({ target: root, clientX: 500, clientY: 300 }, root),
    false,
  ); // 빈 영역
  assert.equal(
    isScrollbarPress({ target: {}, clientX: 1008, clientY: 100 }, root),
    false,
  ); // 버튼 등
});

// --- restoreScroll: 가짜 window로 "문서가 나중에 길어지는" 상황을 흉내 낸다 ---

type Listener = (event: unknown) => void;

class FakeWindow {
  scrollY = 0;
  docHeight = 300; // 처음엔 짧은 문서(내용이 아직 안 그려짐)
  viewport = 300;
  listeners = new Map<string, Set<Listener>>();

  scrollTo(_x: number, y: number): void {
    this.scrollY = Math.max(0, Math.min(y, this.docHeight - this.viewport));
  }
  addEventListener(type: string, listener: Listener): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)?.add(listener);
  }
  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }
  emit(type: string, event: unknown = {}): void {
    for (const listener of [...(this.listeners.get(type) ?? [])])
      listener(event);
  }
  listenerCount(): number {
    return [...this.listeners.values()].reduce((n, set) => n + set.size, 0);
  }
}

let fakeWindow: FakeWindow;
let observers: { callback: () => void; disconnected: boolean }[];
const globals = globalThis as Record<string, unknown>;

beforeEach(() => {
  fakeWindow = new FakeWindow();
  observers = [];
  globals.window = fakeWindow;
  globals.document = {
    documentElement: { clientWidth: 1000, clientHeight: 300 },
  };
  globals.ResizeObserver = class {
    entry = { callback: () => {}, disconnected: false };
    constructor(callback: () => void) {
      this.entry.callback = callback;
      observers.push(this.entry);
    }
    observe(): void {}
    disconnect(): void {
      this.entry.disconnected = true;
    }
  };
});

afterEach(() => {
  delete globals.window;
  delete globals.document;
  delete globals.ResizeObserver;
});

function growDocument(height: number): void {
  fakeWindow.docHeight = height;
  for (const observer of observers)
    if (!observer.disconnected) observer.callback();
}

test("복원: 문서가 나중에(오래 뒤에) 길어져도 위치에 닿으면 끝낸다", () => {
  restoreScroll(500);
  assert.equal(fakeWindow.scrollY, 0); // 짧은 문서라 아직 못 간다

  growDocument(450); // 일부만 그려짐 — 가능한 데까지 가 있다
  assert.equal(fakeWindow.scrollY, 150);
  assert.equal(observers[0].disconnected, false);

  growDocument(1200); // 한참 뒤 전부 그려짐
  assert.equal(fakeWindow.scrollY, 500);
  assert.equal(observers[0].disconnected, true); // 도달해서 관찰 종료
  assert.equal(fakeWindow.listenerCount(), 0); // 리스너도 정리
});

test("복원: 사용자가 스크롤하면(휠/스크롤 키/포인터) 멈추고 더는 끌어가지 않는다", () => {
  for (const [type, event] of [
    ["wheel", {}],
    ["keydown", { key: "PageDown" }],
    [
      "pointerdown",
      {
        target: (globals.document as { documentElement: unknown })
          .documentElement,
        clientX: 1008,
        clientY: 10,
      },
    ],
  ] as const) {
    restoreScroll(500);
    fakeWindow.emit(type, event);
    growDocument(1200);
    assert.equal(fakeWindow.scrollY, 0, type);
    fakeWindow.scrollY = 0;
    fakeWindow.docHeight = 300; // 다음 반복은 다시 짧은 문서에서 시작
    observers.length = 0;
  }
});

test("복원: 내용 위의 일반 클릭이나 피커가 막은 방향키는 멈추지 않는다", () => {
  restoreScroll(500);
  fakeWindow.emit("pointerdown", { target: {}, clientX: 100, clientY: 100 });
  fakeWindow.emit("keydown", {
    key: "ArrowDown",
    defaultPrevented: true,
    target: { tagName: "DIV" },
  });
  growDocument(1200);

  assert.equal(fakeWindow.scrollY, 500);
});

test("복원: Tab 키는 멈추지 않는다", () => {
  restoreScroll(500);
  fakeWindow.emit("keydown", { key: "Tab" });
  growDocument(1200);

  assert.equal(fakeWindow.scrollY, 500);
});

test("복원: 돌려준 함수로 취소하면(화면을 떠남) 이후 크기 변화에 반응하지 않는다", () => {
  const cancel = restoreScroll(500);
  cancel();
  growDocument(1200);

  assert.equal(fakeWindow.scrollY, 0);
  assert.equal(observers[0].disconnected, true);
  assert.equal(fakeWindow.listenerCount(), 0);
});

test("복원: 위치가 0이면 맨 위로 보내고 관찰하지 않는다", () => {
  fakeWindow.scrollY = 40;
  fakeWindow.docHeight = 1000;
  restoreScroll(0);

  assert.equal(fakeWindow.scrollY, 0);
  assert.equal(observers.length, 0);
});

test("복원: 내용이 영영 안 그려져도 90초 뒤에는 관찰을 끝낸다", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    restoreScroll(500);
    assert.equal(observers[0].disconnected, false);

    mock.timers.tick(MAX_RESTORE_MS - 1);
    assert.equal(observers[0].disconnected, false);
    mock.timers.tick(1);

    assert.equal(observers[0].disconnected, true);
    assert.equal(fakeWindow.listenerCount(), 0);
    assert.equal(fakeWindow.scrollY, 0); // 목표에는 못 닿았다
  } finally {
    mock.timers.reset();
  }
});

// --- trackScroll: 복원 중에는 기록에 쓰지 않는다 ---

test("위치 저장: 스크롤마다 한 번 저장하되, 복원 중에는 저장하지 않는다", () => {
  const frames: (() => void)[] = [];
  globals.requestAnimationFrame = (callback: () => void) =>
    frames.push(callback);
  const flush = (): void => {
    for (const frame of frames.splice(0)) frame();
  };
  try {
    const saved: number[] = [];
    trackScroll((y) => saved.push(y));

    fakeWindow.scrollY = 40;
    fakeWindow.emit("scroll");
    fakeWindow.emit("scroll"); // 같은 프레임의 중복은 한 번으로
    flush();
    assert.deepEqual(saved, [40]);

    // 복원 중(내용이 아직 짧아 위치를 못 맞춘 동안)에는 밀린 위치를 덮어쓰지 않는다.
    const cancel = restoreScroll(500);
    fakeWindow.scrollY = 0;
    fakeWindow.emit("scroll");
    flush();
    assert.deepEqual(saved, [40]);

    cancel(); // 복원이 끝나면 다시 저장한다
    fakeWindow.scrollY = 77;
    fakeWindow.emit("scroll");
    flush();
    assert.deepEqual(saved, [40, 77]);
  } finally {
    delete globals.requestAnimationFrame;
  }
});
