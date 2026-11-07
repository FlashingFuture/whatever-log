/** 목표 만들기·수정 요청. 규칙은 로컬 `packages/goals/validation.py`와 같다(서버는 이중으로 확인한다). */
export interface GoalInput {
  name: string;
  nameKey: string;
  dailyTargetMinutes: number;
  /** 월=bit0 … 일=bit6 */
  weekdays: number;
  baseRevision: number;
}

export type GoalParse =
  | { ok: true; value: GoalInput }
  | { ok: false; message: string };

export const NAME_MAX_CHARS = 50;
export const MAX_GOALS = 20;
const FIELDS = new Set([
  "name",
  "daily_target_minutes",
  "weekdays",
  "base_revision",
]);
const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export const isUuid = (value: string): boolean => UUID_V4.test(value);

/**
 * 이름의 비교 키. 로컬(`goals.validation.name_key`)은 NFC + 파이썬 `casefold()`이고, 서버의 키가 그보다 느슨하면(`Straße`와
 * `STRASSE`를 서로 다르다고 보면) 두 목표를 내려받은 PC에서 하나를 저장하지 못한다. JS에는 casefold가 없지만 "대문자로 바꿨다가
 * 소문자로"가 ß→ss, ς→σ, ſ→s, ﬁ→fi 같은 접기를 똑같이 해 준다. 같은 이름의 목표를 둘 못 만들게 하는 키이므로 두 쪽이 맞아야 한다.
 */
export const nameKey = (name: string): string =>
  // 소문자 변환은 어말 시그마를 ς로 바꾸지만 casefold는 항상 σ다.
  name.normalize("NFC").toUpperCase().toLowerCase().replaceAll("ς", "σ");

const isInt = (value: unknown): value is number => Number.isInteger(value);

export function parseGoalInput(body: unknown): GoalParse {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, message: "본문은 JSON 객체여야 합니다." };
  }
  const record = body as Record<string, unknown>;
  const extra = Object.keys(record).filter((key) => !FIELDS.has(key));
  if (extra.length > 0) {
    return {
      ok: false,
      message: `알 수 없는 칸이 있습니다: ${extra.join(", ")}`,
    };
  }
  const {
    name,
    daily_target_minutes: minutes,
    weekdays,
    base_revision: baseRevision,
  } = record;

  if (typeof name !== "string") {
    return { ok: false, message: "name은 문자열이어야 합니다." };
  }
  if (name !== name.normalize("NFC")) {
    return { ok: false, message: "name은 유니코드 NFC여야 합니다." };
  }
  if (/\p{C}/u.test(name)) {
    return { ok: false, message: "name에 제어 문자를 쓸 수 없습니다." };
  }
  if (name !== name.trim()) {
    return { ok: false, message: "name의 앞뒤에 공백이 있으면 안 됩니다." };
  }
  const length = [...name].length;
  if (length < 1 || length > NAME_MAX_CHARS) {
    return { ok: false, message: `name은 1~${NAME_MAX_CHARS}자여야 합니다.` };
  }
  if (!isInt(minutes) || minutes < 1 || minutes > 1440) {
    return {
      ok: false,
      message: "daily_target_minutes는 1~1440 사이의 정수여야 합니다.",
    };
  }
  if (
    !Array.isArray(weekdays) ||
    weekdays.length === 0 ||
    !weekdays.every((day) => isInt(day) && day >= 0 && day <= 6) ||
    new Set(weekdays).size !== weekdays.length
  ) {
    return {
      ok: false,
      message: "weekdays는 0(월)~6(일)의 겹치지 않는 정수 목록이어야 합니다.",
    };
  }
  if (!isInt(baseRevision) || baseRevision < 0) {
    return { ok: false, message: "base_revision은 0 이상의 정수여야 합니다." };
  }
  return {
    ok: true,
    value: {
      name,
      nameKey: nameKey(name),
      dailyTargetMinutes: minutes,
      weekdays: (weekdays as number[]).reduce(
        (bits, day) => bits | (1 << day),
        0,
      ),
      baseRevision,
    },
  };
}
