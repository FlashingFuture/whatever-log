from datetime import UTC, datetime, timedelta

import pytest

from goals import GoalStore
from goals import sync_status as st
from goals.sync_status import describe, read_record, record

NOW = datetime(2026, 11, 7, 3, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    with GoalStore(tmp_path / "goals.db") as opened:
        yield opened


def test_nothing_recorded_reads_as_none(store) -> None:
    assert read_record(store) is None


def test_a_recorded_attempt_round_trips_and_keeps_only_counts_and_kinds(store) -> None:
    written = record(store, result=st.RESULT_OK, problems=2, interval=300, now=NOW)

    assert read_record(store) == written
    assert (written.result, written.problems, written.last_success_at) == ("ok", 2, NOW.isoformat())
    assert set(st.asdict(written)) == {"at", "result", "last_success_at", "problems", "interval"}


def test_a_failure_keeps_the_previous_success_time(store) -> None:
    record(store, result=st.RESULT_OK, problems=0, interval=300, now=NOW)

    failed = record(store, result=st.RESULT_UNREACHABLE, problems=0, interval=300, now=NOW + timedelta(minutes=5))

    assert failed.last_success_at == NOW.isoformat() and failed.at == (NOW + timedelta(minutes=5)).isoformat()


def test_a_skipped_cycle_is_not_a_success(store) -> None:
    skipped = record(store, result=st.RESULT_NOT_ENABLED, problems=0, interval=300, now=NOW)

    assert skipped.last_success_at is None


@pytest.mark.parametrize("raw", ["not json", "[]", "{}", '{"at": "x"}', '{"at": "t", "result": "ok", "problems": "n", "interval": 1}'])
def test_a_corrupted_status_reads_as_missing_not_as_a_crash(store, raw) -> None:
    store.set_meta(st.META_STATUS, raw)

    assert read_record(store) is None


def test_turned_off_is_off_whatever_the_agent_did(store) -> None:
    record(store, result=st.RESULT_UNREACHABLE, problems=0, interval=300, now=NOW)

    assert describe(read_record(store), enabled=False, now=NOW)["state"] == "off"


def test_enabled_without_any_record_is_waiting(store) -> None:
    assert describe(None, enabled=True, now=NOW)["state"] == "waiting"


def test_a_recent_success_is_ok_and_a_recent_failure_is_an_error(store) -> None:
    ok = record(store, result=st.RESULT_OK, problems=1, interval=300, now=NOW)
    assert describe(ok, enabled=True, now=NOW + timedelta(minutes=2)) == {
        "enabled": True,
        "state": "ok",
        "result": "ok",
        "last_attempt_at": NOW.isoformat(),
        "last_success_at": NOW.isoformat(),
        "problems": 1,
    }

    for result in (st.RESULT_UNREACHABLE, st.RESULT_NOT_AUTHORIZED, st.RESULT_SERVER_ERROR, st.RESULT_INTERNAL):
        failed = record(store, result=result, problems=0, interval=300, now=NOW)
        described = describe(failed, enabled=True, now=NOW)
        assert (described["state"], described["result"], described["last_success_at"]) == ("error", result, NOW.isoformat())


def test_skipped_results_are_not_errors(store) -> None:
    for result in (st.RESULT_SIGNED_OUT, st.RESULT_NOT_ENABLED, st.RESULT_ACCOUNT_CHANGED):
        skipped = record(store, result=result, problems=0, interval=300, now=NOW)

        assert describe(skipped, enabled=True, now=NOW)["state"] == "ok"


def test_an_old_record_means_the_agent_is_not_running(store) -> None:
    ok = record(store, result=st.RESULT_OK, problems=0, interval=300, now=NOW)

    assert describe(ok, enabled=True, now=NOW + timedelta(seconds=900))["state"] == "ok"  # 3주기까지는 기다린다
    assert describe(ok, enabled=True, now=NOW + timedelta(seconds=901))["state"] == "stale"


def test_a_short_interval_still_waits_at_least_two_minutes(store) -> None:
    fast = record(store, result=st.RESULT_OK, problems=0, interval=5, now=NOW)

    assert describe(fast, enabled=True, now=NOW + timedelta(seconds=119))["state"] == "ok"
    assert describe(fast, enabled=True, now=NOW + timedelta(seconds=121))["state"] == "stale"


def test_a_stale_agent_that_last_failed_is_stale_not_an_error(store) -> None:
    failed = record(store, result=st.RESULT_UNREACHABLE, problems=0, interval=300, now=NOW)

    assert describe(failed, enabled=True, now=NOW + timedelta(hours=3))["state"] == "stale"


def test_a_record_with_an_unreadable_time_is_stale(store) -> None:
    store.set_meta(st.META_STATUS, '{"at": "garbage", "result": "ok", "last_success_at": null, "problems": 0, "interval": 300}')

    assert describe(read_record(store), enabled=True, now=NOW)["state"] == "stale"


def test_the_account_change_reset_clears_the_status(store) -> None:
    record(store, result=st.RESULT_OK, problems=0, interval=300, now=NOW)

    store.reset_sync()

    assert read_record(store) is None
