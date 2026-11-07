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
 * 이름의 비교 키. 로컬(`goals.validation.name_key`)은 NFC + 파이썬 `casefold()`이고, 서버의 키가 그것과 어긋나면 한쪽에서는 같은
 * 이름이 다른 쪽에서는 다른 이름이 되어 목표를 저장하지 못한다(서버가 더 합치면 로컬에서 만든 두 목표 중 하나가 서버에서 거부되고, 덜 합치면 서버에서
 * 둘로 올라간 목표를 내려받은 PC가 하나를 저장하지 못한다). JS에는 casefold가 없어서, "대문자로 바꿨다가 소문자로"(ß→ss, ſ→s, ﬁ→fi 등)에
 * 어말 시그마 정리를 더해 맞추고, 이것으로 다르게 나오는 두 글자만 따로 처리한다:
 *  - `ı`(점 없는 i): 대문자가 `I`라서 `i`와 합쳐지지만 casefold는 합치지 않는다 → 그대로 둔다.
 *  - `ẞ`(대문자 ß): 소문자가 `ß`라서 `ss`와 갈라지지만 casefold는 `ss`다 → `ss`로 접는다.
 * 글자 단위로 접는다(위 두 예외를 글자 단위로 골라내려고. 문맥에 따라 달라지는 어말 시그마는 따로 정리한다).
 * 두 구현이 같은 묶음을 만드는지는 `packages/goals/tests/test_name_key_parity.py`가 모든 유니코드 글자로 확인한다.
 * 한계: 파이썬과 Workers 런타임의 유니코드 버전이 다르면, 새 버전에서 추가된 글자의 대소문자 관계가 어긋날 수 있다(극히 드문 문자들).
 */
export const nameKey = (name: string): string =>
  [...name.normalize("NFC")]
    .map((char) => {
      if (char === "ı") return char;
      if (char === "ẞ") return "ss";
      return char.toUpperCase().toLowerCase();
    })
    .join("")
    .replaceAll("ς", "σ");

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
