"""목표 입력 검증. 일부러 엄격하다 — 입력의 목적이 분명하다(목표 이름 + 하루 목표 시간 + 요일 +
연결할 프로세스 이름)는 점을 이용해, 모양이 조금이라도 다르면 조용히 고쳐 받지 않고 거부한다.

- 형식(type)을 맞춘다: 숫자 칸에 문자열·불리언을 받지 않고, 목록 칸에 문자열을 받지 않는다.
- 값을 몰래 고치지 않는다: 앞뒤 공백, 중복, 범위 밖 값은 정리해 주지 않고 오류로 알린다.
  (유일한 예외: 목표 이름은 유니코드 NFC로 정규화한다 — 같은 글자의 서로 다른 표현을 같은 것으로 보기 위해서다.)
- 한 번에 모든 칸의 오류를 모아서 알린다.

이 모듈이 규칙의 원본이다. 화면의 즉시 안내는 편의일 뿐이고, 저장 전에는 항상 여기를 거친다.
"""

import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from goals.errors import FieldError, GoalValidationError

NAME_MAX_CHARS = 50
MIN_TARGET_MINUTES = 1
MAX_TARGET_MINUTES = 24 * 60
# 월(0) … 일(6) — 파이썬 date.weekday()와 같다.
WEEKDAYS = frozenset(range(7))
MAX_GOALS = 20
MAX_PROCESSES_PER_GOAL = 20

# Windows 파일 이름에 쓸 수 없는 글자. 프로세스 이름은 exe 파일 이름이라 이것들이 들어갈 수 없다.
_FORBIDDEN_IN_PROCESS_NAME = frozenset('\\/:*?"<>|')
# NTFS의 파일 이름 한 칸 제한은 255 "UTF-16 코드 단위"다. 파이썬의 글자 수(코드 포인트)와 달리 이모지 같은
# 기본 다국어 평면(BMP) 밖 글자는 두 단위를 차지해서, 글자 수로 재면 제한을 넘는 이름이 통과한다.
PROCESS_NAME_MAX_UTF16_UNITS = 255
_PROCESS_SUFFIX = ".exe"
# 확장자가 있어도(`CON.exe`) 파일 이름으로 쓸 수 없는 Windows 예약 장치 이름.
_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{n}" for n in range(1, 10)}
    | {f"lpt{n}" for n in range(1, 10)}
)


@dataclass(frozen=True)
class GoalSpec:
    """검증을 통과한 입력. 저장소는 이 값만 받는다(검증되지 않은 값이 저장되지 않게 타입으로 막는다)."""

    name: str
    name_key: str
    daily_target_minutes: int
    weekdays: frozenset[int]
    # (이름, 비교 키) — 대소문자를 구분하지 않는 키 순서로 정렬돼 같은 입력은 항상 같은 순서다.
    processes: tuple[tuple[str, str], ...]


def _utf16_units(text: str) -> int:
    """글자열이 차지하는 UTF-16 코드 단위 수(NTFS 파일 이름 길이 제한의 단위)."""
    return len(text.encode("utf-16-le")) // 2


def process_key(name: str) -> str:
    """프로세스 이름의 비교 키. Windows 파일 이름은 대소문자를 구분하지 않으므로 casefold로 같게 본다.

    목표에 연결된 프로세스와 기록된 프로세스를 맞춰 볼 때, 그리고 한 프로세스가 두 목표에 연결되는
    것을 막을 때 모두 이 키를 쓴다.
    """
    return name.casefold()


def name_key(name: str) -> str:
    """목표 이름의 비교 키(대소문자·유니코드 표현 차이를 무시). 같은 이름의 목표를 두 개 못 만들게 한다."""
    return unicodedata.normalize("NFC", name).casefold()


def _is_plain_int(value: object) -> bool:
    """값이 진짜 정수인지(True/False 같은 bool은 제외)."""
    # bool은 int의 하위 타입이라 isinstance만으로는 True/False가 숫자로 통과한다.
    return isinstance(value, int) and not isinstance(value, bool)


def _has_control_character(text: str) -> bool:
    """제어·서식 문자가 하나라도 있는지."""
    # 제어 문자와 서식 문자(줄바꿈, 탭, 폭 없는 공백 등)는 눈에 안 보여 구분이 안 되므로 받지 않는다.
    return any(unicodedata.category(char).startswith("C") for char in text)


def _check_name(value: Any, errors: list[FieldError]) -> str | None:
    """이름 칸을 검사해 통과하면 정규화된 이름, 아니면 errors에 한 건을 더하고 None."""
    if not isinstance(value, str):
        errors.append(FieldError("name", "type", "이름은 문자열이어야 합니다."))
        return None
    name = unicodedata.normalize("NFC", value)
    if _has_control_character(name):
        errors.append(FieldError("name", "invalid_characters", "이름에 줄바꿈·탭 같은 제어 문자를 쓸 수 없습니다."))
    elif name != name.strip():
        errors.append(FieldError("name", "whitespace_edges", "이름의 앞뒤에 공백이 있으면 안 됩니다."))
    elif not 1 <= len(name) <= NAME_MAX_CHARS:
        errors.append(FieldError("name", "length", f"이름은 1~{NAME_MAX_CHARS}자여야 합니다."))
    else:
        return name
    return None


def _check_target_minutes(value: Any, errors: list[FieldError]) -> int | None:
    """목표 시간 칸을 검사해 통과하면 정수, 아니면 errors에 한 건을 더하고 None."""
    if not _is_plain_int(value):
        errors.append(FieldError("daily_target_minutes", "type", "목표 시간은 정수(분)여야 합니다."))
        return None
    if not MIN_TARGET_MINUTES <= value <= MAX_TARGET_MINUTES:
        errors.append(
            FieldError(
                "daily_target_minutes",
                "range",
                f"목표 시간은 {MIN_TARGET_MINUTES}~{MAX_TARGET_MINUTES}분이어야 합니다.",
            )
        )
        return None
    return value


def _check_weekdays(value: Any, errors: list[FieldError]) -> frozenset[int] | None:
    """요일 칸을 검사해 통과하면 요일 집합, 아니면 errors에 한 건을 더하고 None."""
    if not isinstance(value, (list, tuple)):
        errors.append(FieldError("weekdays", "type", "요일은 목록(월=0 … 일=6)이어야 합니다."))
        return None
    if not value:
        errors.append(FieldError("weekdays", "empty", "적용할 요일을 하나 이상 골라야 합니다."))
        return None
    if not all(_is_plain_int(day) for day in value):
        errors.append(FieldError("weekdays", "type", "요일은 정수(월=0 … 일=6)여야 합니다."))
        return None
    if not all(day in WEEKDAYS for day in value):
        errors.append(FieldError("weekdays", "range", "요일은 0(월)~6(일)이어야 합니다."))
        return None
    if len(set(value)) != len(value):
        errors.append(FieldError("weekdays", "duplicate", "같은 요일이 두 번 들어 있습니다."))
        return None
    return frozenset(value)


def _process_name_problem(name: str) -> tuple[str, str] | None:
    """프로세스 이름이 올바른 exe 파일 이름이 아니면 (code, 설명), 맞으면 None."""
    if _has_control_character(name):
        return "invalid_characters", "제어 문자가 들어 있습니다."
    if any(char in _FORBIDDEN_IN_PROCESS_NAME for char in name):
        return "invalid_characters", '파일 이름에 쓸 수 없는 글자(\\ / : * ? " < > |)가 있습니다.'
    if name != name.strip():
        return "whitespace_edges", "앞뒤에 공백이 있으면 안 됩니다."
    if not 1 <= _utf16_units(name) <= PROCESS_NAME_MAX_UTF16_UNITS:
        return "length", f"{PROCESS_NAME_MAX_UTF16_UNITS}자(UTF-16 기준) 이하여야 합니다."
    if not name.casefold().endswith(_PROCESS_SUFFIX) or not name[: -len(_PROCESS_SUFFIX)].strip(" ."):
        return "not_exe", "프로세스 이름은 `이름.exe` 꼴이어야 합니다."
    # Windows는 첫 점 앞의 이름이 예약어면 확장자와 상관없이 파일 이름으로 쓰지 못한다.
    if name.split(".", 1)[0].rstrip(" ").casefold() in _RESERVED_DEVICE_NAMES:
        return "reserved_name", "Windows 예약 이름(CON, PRN, AUX, NUL, COM1~9, LPT1~9)은 쓸 수 없습니다."
    return None


def is_valid_process_name(name: object) -> bool:
    """연결할 수 있는 프로세스 이름인지(올바른 `*.exe` 파일 이름). 화면이 고를 수 있는 목록을 거를 때 쓴다 —
    검증과 같은 규칙이라 "목록에는 있는데 연결하면 거부되는" 일이 없다."""
    return isinstance(name, str) and _process_name_problem(name) is None


def _check_processes(
    value: Any, known_processes: Collection[str] | None, errors: list[FieldError]
) -> tuple[tuple[str, str], ...] | None:
    """연결 프로세스 칸(0~20개)을 검사해 통과하면 (이름, 키) 쌍을 키 순으로, 아니면 errors를 더하고 None."""
    if not isinstance(value, (list, tuple)):
        errors.append(FieldError("processes", "type", "연결할 프로세스는 목록이어야 합니다."))
        return None
    # 비어 있어도 된다: 목표를 먼저 만들고 프로세스를 나중에 연결하는 흐름(연결한 프로세스가 없는 목표는
    # 수행 시간이 0일 뿐이다)과, 연결을 하나씩 자유롭게 풀 수 있는 화면을 위해서다.
    if len(value) > MAX_PROCESSES_PER_GOAL:
        errors.append(
            FieldError("processes", "too_many", f"한 목표에는 프로세스를 {MAX_PROCESSES_PER_GOAL}개까지 연결할 수 있습니다.")
        )
        return None

    problems_before = len(errors)
    seen: set[str] = set()
    for index, item in enumerate(value):
        field = f"processes[{index}]"
        if not isinstance(item, str):
            errors.append(FieldError(field, "type", "프로세스 이름은 문자열이어야 합니다."))
            continue
        problem = _process_name_problem(item)
        if problem is not None:
            errors.append(FieldError(field, problem[0], f"`{item}`: {problem[1]}"))
            continue
        if process_key(item) in seen:
            errors.append(FieldError(field, "duplicate", f"`{item}`가 두 번 들어 있습니다."))
            continue
        seen.add(process_key(item))
        if known_processes is not None and item not in known_processes:
            errors.append(
                FieldError(field, "unknown_process", f"`{item}`는 기록된 적이 없는 프로세스입니다.")
            )
    if len(errors) > problems_before:
        return None
    return tuple(sorted(((item, process_key(item)) for item in value), key=lambda pair: pair[1]))


def usable_keys(
    name: Any, processes: Any, errors: Sequence[FieldError]
) -> tuple[str | None, list[tuple[str, str]]]:
    """검증에 실패한 입력에서도 다른 목표와 겹치는지 확인할 수 있는 부분(이름 키, (프로세스 이름, 키) 쌍)을 꺼낸다.

    저장소가 "형식 오류"와 "다른 목표와의 충돌"을 한 번에 알리려고 쓴다 — 이름이 형식은 맞는데 이미
    있는 이름이면, 다른 칸이 틀렸어도 그 충돌까지 같이 알려 사용자가 한 번에 고칠 수 있다. errors에
    오류가 난 칸(이름 전체, 프로세스 개별 항목)은 믿을 수 없어 뺀다.
    """
    failed = {error.field for error in errors}
    key = name_key(name) if isinstance(name, str) and "name" not in failed else None
    pairs: list[tuple[str, str]] = []
    if isinstance(processes, (list, tuple)) and "processes" not in failed:
        for index, item in enumerate(processes):
            if isinstance(item, str) and f"processes[{index}]" not in failed:
                pairs.append((item, process_key(item)))
    return key, pairs


def validate_goal(
    *,
    name: Any,
    daily_target_minutes: Any,
    weekdays: Any,
    processes: Any,
    known_processes: Collection[str] | None = None,
) -> GoalSpec:
    """목표 입력을 엄격하게 검증해 GoalSpec으로 돌려준다. 하나라도 어긋나면 GoalValidationError.

    모든 칸을 검사해서 오류를 한꺼번에 담는다. known_processes를 주면 연결할 프로세스가 그 목록(보통
    recorder가 기록한 이름들)에 정확히 있어야 한다 — 기록된 적 없는 이름을 연결해 달성률이 영원히 0이
    되는 일을 막는다. 이 목록을 알 수 없는 곳(단위 테스트 등)에서는 생략한다.
    """
    errors: list[FieldError] = []
    checked_name = _check_name(name, errors)
    minutes = _check_target_minutes(daily_target_minutes, errors)
    checked_weekdays = _check_weekdays(weekdays, errors)
    checked_processes = _check_processes(processes, known_processes, errors)
    if errors:
        raise GoalValidationError(errors)
    assert checked_name is not None and minutes is not None
    assert checked_weekdays is not None and checked_processes is not None
    return GoalSpec(
        name=checked_name,
        name_key=name_key(checked_name),
        daily_target_minutes=minutes,
        weekdays=checked_weekdays,
        processes=checked_processes,
    )
