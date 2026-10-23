from datetime import UTC, datetime
from unittest.mock import patch

from recorder.sampling import sample_tick


def test_sample_tick_combines_all_three_sources() -> None:
    with (
        patch(
            "recorder.sampling.get_foreground_process_name",
            return_value="Code.exe",
        ),
        patch(
            "recorder.sampling.get_windowed_process_names",
            return_value={"Code.exe", "chrome.exe"},
        ),
        patch("recorder.sampling.get_seconds_since_last_input", return_value=2.5),
    ):
        sample = sample_tick()

    assert sample.foreground_process == "Code.exe"
    assert sample.windowed_processes == frozenset({"Code.exe", "chrome.exe"})
    assert sample.seconds_since_last_input == 2.5
    assert isinstance(sample.sampled_at, datetime)
    assert sample.sampled_at.tzinfo is UTC


def test_sample_tick_handles_no_foreground_process() -> None:
    with (
        patch("recorder.sampling.get_foreground_process_name", return_value=None),
        patch("recorder.sampling.get_windowed_process_names", return_value=set()),
        patch("recorder.sampling.get_seconds_since_last_input", return_value=0.0),
    ):
        sample = sample_tick()

    assert sample.foreground_process is None
    assert sample.windowed_processes == frozenset()
