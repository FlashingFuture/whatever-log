import json

from common import api_error
from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR


def test_exit_codes_are_distinct_and_nonzero() -> None:
    """supervisor가 두 상황을 구분하려면 값이 달라야 하고, 0(정상)이면 안 된다."""
    assert EXIT_ARGUMENT_ERROR != EXIT_ALREADY_RUNNING
    assert 0 not in (EXIT_ARGUMENT_ERROR, EXIT_ALREADY_RUNNING)


def test_error_body_shape() -> None:
    body = api_error.error_body(api_error.INVALID_REQUEST, "잘못됨")

    assert body == {"error": {"code": "invalid_request", "message": "잘못됨"}}
    assert json.loads(json.dumps(body, ensure_ascii=False)) == body


def test_error_codes_are_unique() -> None:
    codes = [api_error.INVALID_REQUEST, api_error.NOT_FOUND, api_error.UNAVAILABLE, api_error.INTERNAL]

    assert len(set(codes)) == len(codes)
