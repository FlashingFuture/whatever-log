import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { isScrollKey, restoreScroll } from "../src/scroll.ts";

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
  globals.document = { documentElement: {} };
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
    ["pointerdown", {}],
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
