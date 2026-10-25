import argparse
from pathlib import Path

import pytest

from recorder.__main__ import MIN_INTERVAL_SECONDS, _interval_type, _lock_path_for_db


def test_accepts_value_at_minimum() -> None:
    """최소값 자체는 거부하지 않고 그대로 통과해야 한다(경계값 포함 여부 확인)."""
    assert _interval_type(str(MIN_INTERVAL_SECONDS)) == MIN_INTERVAL_SECONDS


def test_accepts_value_above_minimum() -> None:
    """최소값보다 큰 평범한 값은 그대로 float로 통과해야 한다."""
    assert _interval_type("5") == 5.0


def test_rejects_value_below_minimum() -> None:
    """최소값보다 조금이라도 작으면 거부해야 한다."""
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("0.5")


def test_rejects_zero_and_negative() -> None:
    """0과 음수는 과도한 조회 루프로 이어질 수 있으니 반드시 거부해야 한다."""
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("-5")


def test_rejects_non_numeric_value() -> None:
    """숫자로 변환할 수 없는 입력은 ValueError가 아니라 ArgumentTypeError로 나와야 한다."""
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("fast")


def test_rejects_nan_and_infinity() -> None:
    """nan/inf는 크기 비교(< MIN_INTERVAL_SECONDS)를 그냥 통과해버리므로 별도로 막아야 한다."""
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("nan")
    with pytest.raises(argparse.ArgumentTypeError):
        _interval_type("inf")


def test_lock_path_is_derived_from_db_path(tmp_path) -> None:
    """lock 경로를 독립 옵션으로 받지 않는 이유 — 같은 DB에 다른 lock 경로를 주면
    두 인스턴스가 각자 lock은 잡은 채로 같은 SQLite 파일에 동시에 쓸 수 있다.
    DB 경로 하나로만 lock 경로가 결정돼야 그 경우를 막을 수 있다.
    """
    db_path = tmp_path / "recorder.db"
    assert _lock_path_for_db(db_path) == db_path.resolve().with_suffix(".lock")


def test_lock_path_for_db_is_same_for_relative_and_absolute_form(tmp_path, monkeypatch) -> None:
    """같은 DB를 상대/절대 경로로 다르게 가리켜도 같은 lock 경로로 모여야 한다
    (resolve()로 정규화하기 때문)."""
    monkeypatch.chdir(tmp_path)
    absolute = tmp_path / "recorder.db"

    assert _lock_path_for_db(Path("recorder.db")) == _lock_path_for_db(absolute)
