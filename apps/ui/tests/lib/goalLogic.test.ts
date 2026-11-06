import assert from "node:assert/strict";
import { test } from "node:test";

import { chooseTopBlocks } from "../../src/lib/goalSummary.ts";
import { formatTarget, formatWeekdays } from "../../src/lib/goalText.ts";
import {
  addProcess,
  addSite,
  decodeTarget,
  encodeTarget,
  removeProcess,
  removeSite,
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

const YT = { browser: "chrome.exe", domain: "youtube.com" };
const DOCS = { browser: "chrome.exe", domain: "docs.python.org" };
const EDGE_YT = { browser: "msedge.exe", domain: "youtube.com" };
const SITE_GOALS = [
  { id: 1, name: "공부", processes: ["Code.exe"], sites: [DOCS] },
  { id: 2, name: "휴식", processes: [], sites: [EDGE_YT] },
];

test("사이트도 연결됨 / 추가할 수 있음 / 다른 목표에 있음으로 나뉜다", () => {
  const split = splitProcesses(
    ["Code.exe", "chrome.exe", "msedge.exe"],
    SITE_GOALS,
    1,
    [YT, DOCS, EDGE_YT, { browser: "chrome.exe", domain: "a.com" }],
  );

  assert.deepEqual(split.linkedSites, [DOCS]);
  assert.deepEqual(split.availableSites, [
    { browser: "chrome.exe", domain: "a.com" },
    YT,
  ]);
  assert.deepEqual(split.takenSitesByOthers, [
    { site: EDGE_YT, goalName: "휴식" },
  ]);
});

test("사이트가 연결된 브라우저는 전체를 추가할 수 없고, 어느 목표 때문인지 알려 준다", () => {
  const split = splitProcesses(
    ["chrome.exe", "msedge.exe", "zoom.exe"],
    SITE_GOALS,
    1,
  );

  assert.deepEqual(split.available, ["zoom.exe"]);
  assert.deepEqual(split.blocked, [
    { process: "chrome.exe", goalName: "공부" }, // 이 목표 자신의 사이트 때문에도 막힌다
    { process: "msedge.exe", goalName: "휴식" },
  ]);
});

test("브라우저 전체가 연결돼 있으면(어느 목표든) 그 안의 사이트는 고를 수 없다", () => {
  const goals = [
    { id: 1, name: "공부", processes: ["chrome.exe"], sites: [] },
    { id: 2, name: "휴식", processes: ["MSEDGE.EXE"], sites: [] },
  ];

  const split = splitProcesses(["chrome.exe"], goals, 1, [YT, EDGE_YT]);

  assert.deepEqual(split.availableSites, []);
});

test("사이트 비교는 브라우저 이름의 대소문자를 무시하고 도메인은 브라우저별로 따로다", () => {
  const goals = [{ id: 2, name: "휴식", processes: [], sites: [EDGE_YT] }];

  const split = splitProcesses([], goals, 1, [
    { browser: "MSEDGE.exe", domain: "youtube.com" },
    YT, // 같은 도메인이라도 크롬의 것은 다른 대상이다
  ]);

  assert.deepEqual(split.availableSites, [YT]);
});

test("사이트 추가·제거는 새 목록을 돌려주고 원본을 바꾸지 않는다", () => {
  const list = [YT];

  assert.deepEqual(addSite(list, DOCS), [DOCS, YT]);
  assert.deepEqual(
    addSite(list, { browser: "CHROME.EXE", domain: "youtube.com" }),
    [YT],
  );
  assert.deepEqual(
    removeSite(list, { browser: "Chrome.exe", domain: "youtube.com" }),
    [],
  );
  assert.deepEqual(list, [YT]);
});

test("끌어다 놓을 때 주고받는 글자는 되돌릴 수 있고, 엉뚱한 글자는 거른다", () => {
  const process = { kind: "process", process: "Code.exe" } as const;
  const site = { kind: "site", site: YT } as const;

  assert.deepEqual(decodeTarget(encodeTarget(process)), process);
  assert.deepEqual(decodeTarget(encodeTarget(site)), site);
  assert.equal(decodeTarget("Code.exe"), null);
  assert.equal(decodeTarget("null"), null);
  assert.equal(decodeTarget('{"kind":"site","site":{"browser":1}}'), null);
  assert.equal(decodeTarget('{"kind":"window","process":"a"}'), null);
});

test("목표 쪽 최장이 사이트면 그 브라우저 전체와 같게 보지 않고 둘 다 보인다", () => {
  const goalTop = {
    process: "chrome.exe",
    active_seconds: 600,
    site: "youtube.com",
  };
  const actual = { process: "chrome.exe", active_seconds: 1200 };

  assert.equal(chooseTopBlocks(goalTop, actual).kind, "goalAndActual");
  assert.equal(
    chooseTopBlocks(
      { process: "chrome.exe", active_seconds: 600, site: null },
      actual,
    ).kind,
    "same",
  );
});

test("대소문자만 다른 이름이 따로 기록돼도 추가 목록에는 한 번만 나온다", () => {
  const split = splitProcesses(["Chrome.exe", "chrome.EXE", "zoom.exe"], [], 1);

  assert.deepEqual(split.available, ["Chrome.exe", "zoom.exe"]);
});

test("서버의 casefold처럼 ß와 ss를 같은 프로세스로 본다", () => {
  const goals = [{ id: 2, name: "운동", processes: ["Straße.exe"] }];

  const split = splitProcesses(["STRASSE.exe", "other.exe"], goals, 1);

  assert.deepEqual(split.available, ["other.exe"]);
  assert.deepEqual(removeProcess(["Straße.exe"], "STRASSE.EXE"), []);
});
