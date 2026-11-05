import pytest

from goals import GoalValidationError, process_key, validate_goal
from goals.validation import MAX_PROCESSES_PER_GOAL, name_key


def _valid(**overrides):
    fields = {
        "name": "공부",
        "daily_target_minutes": 120,
        "weekdays": [0, 1, 2, 3, 4],
        "processes": ["Code.exe", "chrome.exe"],
    }
    fields.update(overrides)
    return validate_goal(**fields)


def _errors(**overrides) -> dict[str, str]:
    """검증을 실패시키고 {칸: 오류 code}를 돌려준다."""
    with pytest.raises(GoalValidationError) as exc_info:
        _valid(**overrides)
    return {error.field: error.code for error in exc_info.value.errors}


def test_a_valid_input_is_normalized_and_sorted() -> None:
    spec = _valid(processes=["Zoom.exe", "Code.exe", "chrome.exe"])

    assert spec.name == "공부"
    assert spec.daily_target_minutes == 120
    assert spec.weekdays == frozenset({0, 1, 2, 3, 4})
    # 대소문자를 구분하지 않는 순서로 정렬돼, 같은 입력은 항상 같은 순서다.
    assert [name for name, _ in spec.processes] == ["chrome.exe", "Code.exe", "Zoom.exe"]


def test_the_name_is_normalized_to_nfc_and_keyed_case_insensitively() -> None:
    decomposed = "공부"  # 한글 자모가 풀어져 있는 표현
    spec = _valid(name=decomposed)

    assert spec.name == "공부"
    assert name_key("Study") == name_key("sTUDY")


@pytest.mark.parametrize(
    ("name", "code"),
    [
        (None, "type"),
        (123, "type"),
        ("", "length"),
        ("가" * 51, "length"),
        (" 공부", "whitespace_edges"),
        ("공부 ", "whitespace_edges"),
        ("공\n부", "invalid_characters"),
        ("공\t부", "invalid_characters"),
        ("공​부", "invalid_characters"),  # 폭 없는 공백
    ],
)
def test_names_are_rejected_not_silently_fixed(name, code) -> None:
    assert _errors(name=name) == {"name": code}


def test_a_name_at_the_length_limit_is_accepted() -> None:
    assert _valid(name="가" * 50).name == "가" * 50


@pytest.mark.parametrize(
    ("minutes", "code"),
    [
        ("120", "type"),
        (120.0, "type"),
        (True, "type"),  # bool은 int의 하위 타입이지만 숫자로 받지 않는다
        (None, "type"),
        (0, "range"),
        (-5, "range"),
        (24 * 60 + 1, "range"),
    ],
)
def test_target_minutes_must_be_a_plain_integer_in_range(minutes, code) -> None:
    assert _errors(daily_target_minutes=minutes) == {"daily_target_minutes": code}


@pytest.mark.parametrize("minutes", [1, 24 * 60])
def test_target_minutes_boundaries_are_accepted(minutes) -> None:
    assert _valid(daily_target_minutes=minutes).daily_target_minutes == minutes


@pytest.mark.parametrize(
    ("weekdays", "code"),
    [
        ("01234", "type"),
        (None, "type"),
        ({0, 1}, "type"),  # 순서 없는 집합은 받지 않는다(목록만)
        ([], "empty"),
        (["0"], "type"),
        ([True], "type"),
        ([1.0], "type"),
        ([7], "range"),
        ([-1], "range"),
        ([1, 1], "duplicate"),
    ],
)
def test_weekdays_must_be_a_non_empty_list_of_unique_days(weekdays, code) -> None:
    assert _errors(weekdays=weekdays) == {"weekdays": code}


@pytest.mark.parametrize(
    "name",
    [
        "chrome.exe",
        "Docker Desktop.exe",  # 공백이 중간에 있는 실제 이름
        "Battle.net.exe",
        "Arknights_KR_Gamelauncher.exe",
        "CHROME.EXE",
        "메모장.exe",
    ],
)
def test_real_world_process_names_are_accepted(name) -> None:
    assert _valid(processes=[name]).processes[0][0] == name


@pytest.mark.parametrize(
    ("name", "code"),
    [
        (5, "type"),
        (None, "type"),
        ("", "length"),
        ("notexe", "not_exe"),
        ("script.py", "not_exe"),
        ("setup.tmp", "not_exe"),  # 설치 도구가 남기는 .tmp 프로세스는 연결 대상이 아니다
        (".exe", "not_exe"),
        (" .exe", "whitespace_edges"),
        ("...exe", "not_exe"),
        (" chrome.exe", "whitespace_edges"),
        ("chrome.exe ", "whitespace_edges"),
        ("C:\\Windows\\chrome.exe", "invalid_characters"),
        ("a/b.exe", "invalid_characters"),
        ("a*.exe", "invalid_characters"),
        ("a|b.exe", "invalid_characters"),
        ("a\x00b.exe", "invalid_characters"),
        ("a\nb.exe", "invalid_characters"),
        ("가" * 252 + ".exe", "length"),
    ],
)
def test_process_names_must_be_valid_exe_file_names(name, code) -> None:
    assert _errors(processes=[name]) == {"processes[0]": code}


def test_processes_must_be_a_non_empty_list_within_the_limit() -> None:
    assert _errors(processes="chrome.exe") == {"processes": "type"}
    assert _errors(processes=None) == {"processes": "type"}
    assert _errors(processes=[]) == {"processes": "empty"}
    too_many = [f"app{i}.exe" for i in range(MAX_PROCESSES_PER_GOAL + 1)]
    assert _errors(processes=too_many) == {"processes": "too_many"}
    at_limit = [f"app{i}.exe" for i in range(MAX_PROCESSES_PER_GOAL)]
    assert len(_valid(processes=at_limit).processes) == MAX_PROCESSES_PER_GOAL


def test_duplicate_processes_are_rejected_case_insensitively() -> None:
    assert _errors(processes=["chrome.exe", "Chrome.exe"]) == {"processes[1]": "duplicate"}
    assert process_key("Chrome.EXE") == process_key("chrome.exe")


def test_unknown_processes_are_rejected_when_the_recorded_names_are_given() -> None:
    known = {"chrome.exe", "Code.exe"}

    assert _errors(processes=["chrome.exe", "nope.exe"], known_processes=known) == {
        "processes[1]": "unknown_process"
    }
    # 이름은 정확히 일치해야 한다(기록된 이름 그대로 고르는 입력이다).
    assert _errors(processes=["Chrome.exe"], known_processes=known) == {"processes[0]": "unknown_process"}
    assert _valid(processes=["chrome.exe", "Code.exe"], known_processes=known)


def test_all_field_errors_are_reported_at_once() -> None:
    errors = _errors(name="", daily_target_minutes=0, weekdays=[], processes=["x"])

    assert errors == {
        "name": "length",
        "daily_target_minutes": "range",
        "weekdays": "empty",
        "processes[0]": "not_exe",
    }


def test_error_messages_are_readable_korean_and_the_exception_summarizes_them() -> None:
    with pytest.raises(GoalValidationError) as exc_info:
        _valid(name="", daily_target_minutes=0)

    assert all(error.message for error in exc_info.value.errors)
    assert "name:" in str(exc_info.value) and "daily_target_minutes:" in str(exc_info.value)
