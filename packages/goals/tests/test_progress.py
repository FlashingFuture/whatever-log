from goals import Goal, compute_progress

NOW = "2026-11-05T00:00:00+00:00"


def _goal(goal_id: int, name: str, processes: tuple[str, ...]) -> Goal:
    return Goal(
        id=goal_id,
        name=name,
        daily_target_minutes=60,
        weekdays=frozenset(range(7)),
        processes=processes,
        created_at=NOW,
        updated_at=NOW,
    )


def test_a_goals_time_is_the_sum_of_its_processes_active_time() -> None:
    goals = [_goal(1, "공부", ("Code.exe", "chrome.exe")), _goal(2, "운동", ("Zoom.exe",))]

    progress, summary = compute_progress(
        goals, {"Code.exe": 600.0, "chrome.exe": 300.0, "Zoom.exe": 120.0, "Other.exe": 9999.0}
    )

    assert [(item.name, item.active_seconds) for item in progress] == [("공부", 900.0), ("운동", 120.0)]
    assert summary.active_seconds == 1020.0  # 연결되지 않은 프로세스는 세지 않는다
    assert summary.top is not None and (summary.top.process, summary.top.active_seconds) == ("Code.exe", 600.0)


def test_linked_processes_without_recorded_time_are_listed_with_zero() -> None:
    [item], summary = compute_progress([_goal(1, "공부", ("Code.exe", "never.exe"))], {"Code.exe": 60.0})

    assert [(time.process, time.active_seconds) for time in item.processes] == [
        ("Code.exe", 60.0),
        ("never.exe", 0.0),
    ]
    assert summary.active_seconds == 60.0


def test_process_names_match_case_insensitively_and_case_variants_are_merged() -> None:
    """Windows 파일 이름은 대소문자를 구분하지 않는다 — 대소문자만 다르게 기록된 시간은 같은 프로세스."""
    [item], _ = compute_progress(
        [_goal(1, "공부", ("chrome.exe",))], {"chrome.exe": 100.0, "Chrome.EXE": 50.0}
    )

    assert item.active_seconds == 150.0


def test_no_goals_or_no_activity_gives_an_empty_summary() -> None:
    assert compute_progress([], {"Code.exe": 10.0}) == ([], compute_progress([], {})[1])
    _, summary = compute_progress([_goal(1, "공부", ("Code.exe",))], {})

    assert summary.active_seconds == 0.0 and summary.top is None


def test_a_goal_without_processes_has_zero_time() -> None:
    [item], summary = compute_progress([_goal(1, "새 목표", ())], {"Code.exe": 100.0})

    assert item.processes == () and item.active_seconds == 0.0 and summary.top is None


def test_ties_pick_the_name_that_sorts_first_regardless_of_input_order() -> None:
    goals = [_goal(1, "A", ("b.exe",)), _goal(2, "B", ("A.exe",))]

    _, summary = compute_progress(goals, {"b.exe": 30.0, "A.exe": 30.0})

    assert summary.top is not None and summary.top.process == "A.exe"


def test_float_noise_does_not_break_a_tie() -> None:
    goals = [_goal(1, "A", ("z.exe",)), _goal(2, "B", ("a.exe",))]

    _, summary = compute_progress(goals, {"z.exe": 0.1 + 0.2, "a.exe": 0.3})

    assert summary.top is not None and summary.top.process == "a.exe"
