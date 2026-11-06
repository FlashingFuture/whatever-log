// 동기화 확인 창("서버에 넘길 목표를 고르세요")의 순수 로직: 기본 선택, 항목 설명, 결과 요약.
// DOM·hub를 모르므로(lib 층) 필요한 모양만 구조로 받는다 — api의 SyncItem·SyncResult가 그대로 들어온다.

import { formatTarget, formatWeekdays } from "./goalText.ts";

export interface BoardItem {
  key: string;
  kind: "upload" | "merge" | "download";
  name: string;
  daily_target_minutes: number;
  weekdays: readonly number[];
  local_daily_target_minutes: number | null;
  local_weekdays: readonly number[] | null;
  declined: boolean;
}

export interface BoardResult {
  uploaded: number;
  merged: number;
  downloaded: number;
  kept_local: number;
  errors: readonly { key: string; message: string }[];
}

/**
 * 처음 선택해 둘 항목: 전부. 다만 전에 "올리지 않기"를 골랐던 목표는 꺼 둔다 — 사용자가 한 선택을 다음 확인에서
 * 말없이 뒤집지 않으려는 것이다.
 */
export function initialSelection(items: readonly BoardItem[]): Set<string> {
  return new Set(
    items.filter((item) => !item.declined).map((item) => item.key),
  );
}

/** 항목을 "넘김"(true)·"넘기지 않음"(false) 쪽으로 옮긴 새 선택. 목록에 없는 key는 무시한다. */
export function moveItem(
  items: readonly BoardItem[],
  selection: ReadonlySet<string>,
  key: string,
  selected: boolean,
): Set<string> {
  const next = new Set(selection);
  if (!items.some((item) => item.key === key)) {
    return next;
  }
  if (selected) {
    next.add(key);
  } else {
    next.delete(key);
  }
  return next;
}

/** 목표 이름 아래에 보여 줄 값: 서버로 올라가는(또는 서버에서 오는) 목표 시간과 요일. */
export function itemMeta(item: BoardItem): string {
  return `${formatTarget(item.daily_target_minutes)} · ${formatWeekdays(item.weekdays)}`;
}

/** 항목 종류의 짧은 설명(꼬리표). 선택했을 때 무슨 일이 일어나는지를 알려 준다. */
export function itemTag(item: BoardItem): string {
  switch (item.kind) {
    case "upload":
      return "서버에 새로 추가";
    case "merge":
      return "서버의 같은 이름 목표와 합침";
    case "download":
      return "서버에서 이 PC로 가져옴";
  }
}

/**
 * 합치기에서 이 PC의 값과 서버의 값이 다르면 알려 줄 문장(같으면 null). 합치면 목표 시간·요일이 서버 값으로
 * 맞춰지므로, 사용자가 놀라지 않게 선택하기 전에 두 값을 함께 보여 준다.
 */
export function mergeNote(item: BoardItem): string | null {
  if (
    item.kind !== "merge" ||
    item.local_daily_target_minutes === null ||
    item.local_weekdays === null
  ) {
    return null;
  }
  const same =
    item.local_daily_target_minutes === item.daily_target_minutes &&
    formatWeekdays(item.local_weekdays) === formatWeekdays(item.weekdays);
  if (same) {
    return null;
  }
  const local = `${formatTarget(item.local_daily_target_minutes)} · ${formatWeekdays(item.local_weekdays)}`;
  return `합치면 서버의 값으로 맞춰져요 (이 PC: ${local})`;
}

/** 선택에 따라 무슨 일이 일어날지 한 줄로: "3개를 서버에 넘기고, 1개는 이 PC에만 둡니다". */
export function selectionSummary(
  items: readonly BoardItem[],
  selection: ReadonlySet<string>,
): string {
  const chosen = items.filter((item) => selection.has(item.key));
  const upload = chosen.filter((item) => item.kind === "upload").length;
  const merge = chosen.filter((item) => item.kind === "merge").length;
  const download = chosen.filter((item) => item.kind === "download").length;
  const local = items.filter(
    (item) => item.kind !== "download" && !selection.has(item.key),
  ).length;
  const parts: string[] = [];
  if (upload > 0) {
    parts.push(`${upload}개를 서버에 추가`);
  }
  if (merge > 0) {
    parts.push(`${merge}개를 서버 목표와 합침`);
  }
  if (download > 0) {
    parts.push(`${download}개를 이 PC로 가져옴`);
  }
  if (local > 0) {
    parts.push(`${local}개는 이 PC에만 둠`);
  }
  return parts.length === 0 ? "바꿀 것이 없어요" : parts.join(" · ");
}

/** 적용이 끝난 뒤 보여 줄 요약. 실패한 항목이 있어도 성공한 것은 그대로 알린다. */
export function resultSummary(result: BoardResult): string {
  const parts: string[] = [];
  if (result.uploaded > 0) {
    parts.push(`${result.uploaded}개를 서버에 추가했어요`);
  }
  if (result.merged > 0) {
    parts.push(`${result.merged}개를 서버 목표와 합쳤어요`);
  }
  if (result.downloaded > 0) {
    parts.push(`${result.downloaded}개를 이 PC로 가져왔어요`);
  }
  if (result.kept_local > 0) {
    parts.push(`${result.kept_local}개는 이 PC에만 뒀어요`);
  }
  return parts.length === 0 ? "바뀐 것이 없어요" : parts.join(" · ");
}

/** 새로 만든 결과에서 실패한 항목의 이름을 찾아 "이름: 사유"로. 계획에 없는 key는 사유만 보여 준다. */
export function errorLines(
  items: readonly BoardItem[],
  result: BoardResult,
): string[] {
  return result.errors.map(({ key, message }) => {
    const item = items.find((candidate) => candidate.key === key);
    return item ? `${item.name}: ${message}` : message;
  });
}
