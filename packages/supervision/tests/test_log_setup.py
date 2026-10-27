import logging

import pytest

from supervision.log_setup import configure_logging


@pytest.fixture
def test_logger():
    """실제 사용처 로거와 분리된, 테스트 전용 로거. 테스트가 끝나면 핸들러를 치운다."""
    logger = logging.getLogger("supervision.test_log_setup")
    yield logger
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)


def test_configure_logging_writes_to_file(tmp_path, test_logger) -> None:
    """콘솔이 없는 백그라운드 실행을 가정 — 파일 핸들러로 실제 로그가 남아야 한다."""
    log_path = tmp_path / "recorder.log"
    configure_logging(test_logger, log_path)
    test_logger.info("hello")
    for handler in test_logger.handlers:
        handler.flush()

    assert "hello" in log_path.read_text(encoding="utf-8")


def test_configure_logging_is_idempotent(tmp_path, test_logger) -> None:
    """같은 프로세스에서 다시 불려도(테스트 등) 핸들러가 중복으로 쌓이면 안 된다."""
    configure_logging(test_logger, tmp_path / "a.log")
    handler_count_after_first = len(test_logger.handlers)

    configure_logging(test_logger, tmp_path / "b.log")

    assert len(test_logger.handlers) == handler_count_after_first
