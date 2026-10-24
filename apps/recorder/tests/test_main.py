import argparse
import logging

import pytest

from recorder.__main__ import MIN_INTERVAL_SECONDS, _configure_logging, _interval_type, logger


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


def test_configure_logging_writes_to_file(tmp_path) -> None:
    """콘솔이 없는 백그라운드 실행을 가정 — 파일 핸들러로 실제 로그가 남아야 한다."""
    log_path = tmp_path / "recorder.log"
    _configure_logging(log_path)
    logger.info("hello")
    for handler in logger.handlers:
        handler.flush()

    assert "hello" in log_path.read_text(encoding="utf-8")


def test_configure_logging_is_idempotent(tmp_path) -> None:
    """같은 프로세스에서 다시 불려도(테스트 등) 핸들러가 중복으로 쌓이면 안 된다."""
    _configure_logging(tmp_path / "a.log")
    handler_count_after_first = len(logger.handlers)

    _configure_logging(tmp_path / "b.log")

    assert len(logger.handlers) == handler_count_after_first


@pytest.fixture(autouse=True)
def _reset_logger_handlers():
    yield
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
