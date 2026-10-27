import argparse
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recorder import __main__ as main_module
from recorder.__main__ import MIN_INTERVAL_SECONDS, _interval_type, _lock_path_for_db
from supervision.log_setup import configure_logging


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
    resolved = db_path.resolve()
    assert _lock_path_for_db(db_path) == resolved.with_name(f"{resolved.name}.lock")


def test_lock_path_for_db_is_same_for_relative_and_absolute_form(tmp_path, monkeypatch) -> None:
    """같은 DB를 상대/절대 경로로 다르게 가리켜도 같은 lock 경로로 모여야 한다
    (resolve()로 정규화하기 때문)."""
    monkeypatch.chdir(tmp_path)
    absolute = tmp_path / "recorder.db"

    assert _lock_path_for_db(Path("recorder.db")) == _lock_path_for_db(absolute)


def test_lock_path_does_not_collide_across_different_db_extensions(tmp_path) -> None:
    """recorder.db와 recorder.sqlite처럼 stem은 같고 확장자만 다른 DB는 서로 다른
    DB이므로 lock 경로도 달라야 한다 — with_suffix로 확장자를 바꾸면 둘 다
    recorder.lock으로 겹쳐서 서로 다른 DB에 대한 lock이 충돌해버린다."""
    assert _lock_path_for_db(tmp_path / "recorder.db") != _lock_path_for_db(
        tmp_path / "recorder.sqlite"
    )


def test_run_logs_when_open_db_fails(tmp_path, monkeypatch) -> None:
    """open_db() 실패는 틱 루프의 except Exception보다 바깥이라, 따로 감싸지
    않으면 로그에 안 남고 그냥 전파된다 — pythonw.exe 환경에서는 stderr도 None이라
    원인이 어디에도 안 남는다. lock은 실패하더라도 정상 해제돼야 한다.
    """
    configure_logging(main_module.logger, tmp_path / "recorder.log")

    fake_lock = MagicMock()
    monkeypatch.setattr(main_module, "acquire_lock", lambda _path: fake_lock)
    monkeypatch.setattr(
        main_module, "open_db", MagicMock(side_effect=RuntimeError("disk full"))
    )

    with pytest.raises(RuntimeError, match="disk full"):
        main_module.run(5.0, tmp_path / "recorder.db")

    fake_lock.release.assert_called_once()
    for handler in main_module.logger.handlers:
        handler.flush()
    log_content = (tmp_path / "recorder.log").read_text(encoding="utf-8")
    assert "DB를 열지 못했습니다" in log_content


@pytest.fixture(autouse=True)
def _reset_main_logger_handlers():
    yield
    main_module.logger.handlers.clear()
