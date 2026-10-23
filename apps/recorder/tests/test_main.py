import argparse

import pytest

from recorder.__main__ import MIN_INTERVAL_SECONDS, _interval_type


def test_accepts_value_at_minimum() -> None:
    assert _interval_type(str(MIN_INTERVAL_SECONDS)) == MIN_INTERVAL_SECONDS


def test_accepts_value_above_minimum() -> None:
    assert _interval_type("5") == 5.0


def test_rejects_value_below_minimum() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("0.5")


def test_rejects_zero_and_negative() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("-5")


def test_rejects_non_numeric_value() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("fast")
