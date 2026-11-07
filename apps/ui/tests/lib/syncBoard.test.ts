import assert from "node:assert/strict";
import { test } from "node:test";

import {
  type BoardItem,
  errorLines,
  initialSelection,
  itemMeta,
  itemTag,
  mergeNote,
  moveItem,
  resultSummary,
  selectionSummary,
} from "../../src/lib/syncBoard.ts";

function item(over: Partial<BoardItem> = {}): BoardItem {
  return {
    key: "local:1",
    kind: "upload",
    name: "공부",
    daily_target_minutes: 120,
    weekdays: [0, 1, 2, 3, 4],
    local_daily_target_minutes: null,
    local_weekdays: null,
    declined: false,
    ...over,
  };
}

const UPLOAD = item();
const MERGE = item({
  key: "local:2",
  kind: "merge",
  name: "운동",
  daily_target_minutes: 60,
  weekdays: [5, 6],
  local_daily_target_minutes: 30,
  local_weekdays: [0],
});
const DOWNLOAD = item({ key: "remote:r-1", kind: "download", name: "독서" });
const DECLINED = item({ key: "local:3", name: "비공개", declined: true });

test("처음에는 전부 선택하되, 전에 올리지 않기로 한 목표는 꺼 둔다", () => {
  const selection = initialSelection([UPLOAD, MERGE, DOWNLOAD, DECLINED]);

  assert.deepEqual([...selection].sort(), ["local:1", "local:2", "remote:r-1"]);
});

test("항목을 옮기면 새 선택이 만들어지고 원래 선택은 그대로다", () => {
  const items = [UPLOAD, MERGE];
  const before = new Set(["local:1"]);

  const added = moveItem(items, before, "local:2", true);
  const removed = moveItem(items, added, "local:1", false);

  assert.deepEqual([...added].sort(), ["local:1", "local:2"]);
  assert.deepEqual([...removed], ["local:2"]);
  assert.deepEqual([...before], ["local:1"]);
});

test("목록에 없는 key는 선택에 들어가지 않는다", () => {
  const next = moveItem([UPLOAD], new Set(), "local:999", true);

  assert.equal(next.size, 0);
});

test("항목의 값은 목표 시간과 요일을 사람이 읽는 글자로 보여 준다", () => {
  assert.equal(itemMeta(UPLOAD), "2시간 · 평일");
  assert.equal(itemMeta(MERGE), "1시간 · 주말");
});

test("꼬리표는 선택했을 때 일어날 일을 알려 준다", () => {
  assert.equal(itemTag(UPLOAD, true), "서버에 새로 추가");
  assert.equal(itemTag(MERGE, true), "서버의 같은 이름 목표와 합침");
  assert.equal(itemTag(DOWNLOAD, true), "서버에서 이 PC로 가져옴");
});

test("선택하지 않은 항목은 실제로 어디에 남는지 알려 준다: 서버에만 있던 목표는 이 PC에 없다", () => {
  assert.equal(itemTag(UPLOAD, false), "이 PC에만 둠");
  assert.equal(itemTag(MERGE, false), "이 PC에만 둠");
  assert.equal(
    itemTag(DOWNLOAD, false),
    "서버에만 있음 · 이 PC로 가져오지 않음",
  );
});

test("합치기에서 값이 다르면 이 PC의 값을 함께 알려 주고, 같거나 합치기가 아니면 알리지 않는다", () => {
  assert.equal(
    mergeNote(MERGE),
    "합치면 서버의 값으로 맞춰져요 (이 PC: 30분 · 월)",
  );
  assert.equal(
    mergeNote(
      item({
        ...MERGE,
        local_daily_target_minutes: 60,
        local_weekdays: [6, 5],
      }),
    ),
    null,
  );
  assert.equal(mergeNote(UPLOAD), null);
  assert.equal(mergeNote(DOWNLOAD), null);
});

test("선택 요약: 무엇을 넘기고 무엇을 이 PC에만 두는지", () => {
  const items = [UPLOAD, MERGE, DOWNLOAD, DECLINED];

  assert.equal(
    selectionSummary(items, new Set(["local:1", "local:2", "remote:r-1"])),
    "1개를 서버에 추가 · 1개를 서버 목표와 합침 · 1개를 이 PC로 가져옴 · 1개는 이 PC에만 둠",
  );
  assert.equal(selectionSummary(items, new Set()), "3개는 이 PC에만 둠"); // 가져오기(download)는 "이 PC에만 둠"이 아니다
  assert.equal(selectionSummary([DOWNLOAD], new Set()), "바꿀 것이 없어요");
});

test("가져오기를 체크하지 않은 것은 이 PC에만 두는 목표로 세지 않는다", () => {
  assert.equal(selectionSummary([DOWNLOAD], new Set()), "바꿀 것이 없어요");
});

test("결과 요약과 실패 줄", () => {
  const result = {
    uploaded: 2,
    merged: 0,
    downloaded: 1,
    kept_local: 1,
    errors: [
      { key: "local:1", message: "서버에 같은 이름의 목표가 이미 있습니다." },
      { key: "local:zzz", message: "알 수 없는 오류" },
    ],
  };

  assert.equal(
    resultSummary(result),
    "2개를 서버에 추가했어요 · 1개를 이 PC로 가져왔어요 · 1개는 이 PC에만 뒀어요",
  );
  assert.deepEqual(errorLines([UPLOAD], result), [
    "공부: 서버에 같은 이름의 목표가 이미 있습니다.",
    "알 수 없는 오류",
  ]);
  assert.equal(
    resultSummary({
      uploaded: 0,
      merged: 0,
      downloaded: 0,
      kept_local: 0,
      errors: [],
    }),
    "바뀐 것이 없어요",
  );
});
