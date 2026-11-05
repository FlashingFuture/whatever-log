import assert from "node:assert/strict";
import { test } from "node:test";

import { chooseTopBlocks } from "../../src/lib/goalSummary.ts";
import { formatTarget, formatWeekdays } from "../../src/lib/goalText.ts";
import {
  addProcess,
  removeProcess,
  splitProcesses,
} from "../../src/lib/processPick.ts";

test("적용 요일을 짧은 글자로", () => {
  assert.equal(formatWeekdays([0, 1, 2, 3, 4, 5, 6]), "매일");
  assert.equal(formatWeekdays([4, 3, 2, 1, 0]), "평일"); // 순서가 뒤섞여도
  assert.equal(formatWeekdays([5, 6]), "주말");
  assert.equal(formatWeekdays([0, 2, 4]), "월·수·금");
  assert.equal(formatWeekdays([2, 2, 0]), "월·수"); // 중복은 정리
  assert.equal(formatWeekdays([0, 1, 2, 3, 4, 5]), "월·화·수·목·금·토");
  assert.equal(formatWeekdays([]), "");
});

test("목표 시간을 읽기 좋게", () => {
  assert.equal(formatTarget(45), "45분");
  assert.equal(formatTarget(60), "1시간");
  assert.equal(formatTarget(90), "1시간 30분");
  assert.equal(formatTarget(1440), "24시간");
});

const GOALS = [
  { id: 1, name: "공부", processes: ["Code.exe", "chrome.exe"] },
  { id: 2, name: "운동", processes: ["Zoom.exe"] },
];

test("연결 화면의 세 목록: 연결됨 / 추가할 수 있음 / 다른 목표에 있음", () => {
  const tracked = [
    "chrome.exe",
    "Code.exe",
    "Zoom.exe",
    "Anki.exe",
    "Slack.exe",
  ];

  const split = splitProcesses(tracked, GOALS, 1);

  assert.deepEqual(split.linked, ["chrome.exe", "Code.exe"]); // 이름(대소문자 무시) 순
  assert.deepEqual(split.available, ["Anki.exe", "Slack.exe"]);
  assert.deepEqual(split.takenByOthers, [
    { process: "Zoom.exe", goalName: "운동" },
  ]);
});

test("다른 목표의 프로세스는 추가할 수 없고, 대소문자만 달라도 같은 프로세스다", () => {
  const split = splitProcesses(["zoom.exe", "ZOOM.EXE", "new.exe"], GOALS, 1);

  assert.deepEqual(split.available, ["new.exe"]);
});

test("지금은 추적되지 않아도 이미 연결된 프로세스는 연결 목록에 남는다", () => {
  const split = splitProcesses([], GOALS, 1);

  assert.deepEqual(split.linked, ["chrome.exe", "Code.exe"]);
  assert.deepEqual(split.available, []);
});

test("새 목표(연결 없음)는 아직 어디에도 안 쓰인 프로세스만 추가할 수 있다", () => {
  const split = splitProcesses(["Code.exe", "Anki.exe"], GOALS, 99);

  assert.deepEqual(split.linked, []);
  assert.deepEqual(split.available, ["Anki.exe"]);
});

test("프로세스 추가·제거는 새 목록을 돌려주고 원본을 바꾸지 않는다", () => {
  const list = ["b.exe", "a.exe"];

  assert.deepEqual(addProcess(list, "C.exe"), ["a.exe", "b.exe", "C.exe"]);
  assert.deepEqual(addProcess(list, "A.EXE"), ["a.exe", "b.exe"]); // 이미 있으면 그대로
  assert.deepEqual(removeProcess(list, "B.exe"), ["a.exe"]); // 대소문자 무시
  assert.deepEqual(list, ["b.exe", "a.exe"]);
});

const A = { process: "Code.exe", active_seconds: 600 };
const B = { process: "chrome.exe", active_seconds: 1200 };

test("목표 최장과 실제 최장이 같으면 하나만 보인다", () => {
  assert.deepEqual(chooseTopBlocks(A, { ...A }), { kind: "same", top: A });
  assert.equal(
    chooseTopBlocks(A, { process: "CODE.EXE", active_seconds: 600 }).kind,
    "same",
  );
});

test("다르면 둘 다 보인다", () => {
  assert.deepEqual(chooseTopBlocks(A, B), {
    kind: "goalAndActual",
    goalTop: A,
    actualTop: B,
  });
});

test("목표 쪽 프로세스가 없으면 실제 최장만 보인다", () => {
  assert.deepEqual(chooseTopBlocks(null, B), {
    kind: "actualOnly",
    actualTop: B,
  });
  assert.deepEqual(chooseTopBlocks(null, null), {
    kind: "actualOnly",
    actualTop: null,
  });
});
