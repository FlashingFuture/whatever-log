import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canDelete,
  type DeviceLike,
  deleteWarning,
  deviceLabel,
  sortDevices,
} from "../../src/lib/devices.ts";

const device = (over: Partial<DeviceLike> = {}): DeviceLike => ({
  device_id: "aaaaaa11-0000-4000-8000-000000000000",
  last_sent_at: "2026-11-06T03:00:00.000Z",
  rows: 3,
  is_this_device: false,
  ...over,
});

test("이 기기가 맨 위, 나머지는 최근에 보낸 순, 같으면 기기 ID 순이다", () => {
  const old = device({
    device_id: "b",
    last_sent_at: "2026-11-01T00:00:00.000Z",
  });
  const recentB = device({
    device_id: "d",
    last_sent_at: "2026-11-05T00:00:00.000Z",
  });
  const recentA = device({
    device_id: "c",
    last_sent_at: "2026-11-05T00:00:00.000Z",
  });
  const mine = device({
    device_id: "a",
    last_sent_at: "2026-10-01T00:00:00.000Z",
    is_this_device: true,
  });

  assert.deepEqual(
    sortDevices([old, recentB, mine, recentA]).map((d) => d.device_id),
    ["a", "c", "d", "b"],
  );
});

test("정렬은 원래 목록을 바꾸지 않는다", () => {
  const list = [device({ device_id: "b" }), device({ device_id: "a" })];

  sortDevices(list);

  assert.deepEqual(
    list.map((d) => d.device_id),
    ["b", "a"],
  );
});

test("기기에는 이름이 없어 ID 앞 6글자로 구분하고, 이 기기는 이 기기라고 부른다", () => {
  assert.equal(deviceLabel(device({ is_this_device: true }), 1), "이 기기");
  assert.equal(deviceLabel(device(), 2), "다른 기기 2 (aaaaaa)");
});

test("이 기기의 기록은 지울 수 없고 다른 기기만 지울 수 있다", () => {
  assert.equal(canDelete(device({ is_this_device: true })), false);
  assert.equal(canDelete(device()), true);
});

test("삭제 경고는 지워지는 줄 수와, 그대로인 것을 알려 준다", () => {
  const text = deleteWarning(device({ rows: 12 }));

  assert.match(text, /12줄/);
  assert.match(text, /목표와 다른 기기의 기록은 그대로/);
});
