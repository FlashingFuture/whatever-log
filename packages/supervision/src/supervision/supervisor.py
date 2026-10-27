"""자식 프로세스를 띄우고, 비정상 종료하면 재시작하는 범용 supervisor 루프.

원래 recorder 전용으로 있었다(apps/recorder) — hub도 똑같은 모양의 문제(자식
프로세스를 띄우고, 크래시면 재시작하되 크래시 루프는 포기하고 멈춘다)를
풀어야 해서 공통 모듈로 뺐다. "어떤 종료 코드가 재시도해도 안 풀리는
상황인지"는 호출부마다 다르므로(recorder는 EXIT_ARGUMENT_ERROR/
EXIT_ALREADY_RUNNING, hub는 EXIT_ALREADY_RUNNING만) classify_exit 콜백으로
받는다.
"""

import logging
import subprocess
import time
from collections.abc import Callable
from threading import Event

RESTART_DELAY_SECONDS = 5.0

# 디스크 꽉 찬 경우나 DB 영구 손상처럼 재시도해도 절대 안 풀리는 문제를
# classify_exit로 미리 분류해둘 수는 없다. 대신 "뜨자마자 바로 죽는" 패턴이
# 연속으로 반복되면 크래시 루프로 보고 재시작을 멈춘다.
MAX_CONSECUTIVE_FAILURES = 5
# 이 시간 이상 버티고 나서 죽은 거라면 크래시 루프가 아니라 "오래 쓰다가 가끔
# 한 번씩 죽은 것"으로 보고 연속 실패 횟수를 리셋한다.
MIN_STABLE_RUN_SECONDS = 60.0


def supervise(
    command: list[str],
    *,
    logger: logging.Logger,
    classify_exit: Callable[[int], str | None],
    restart_delay_seconds: float = RESTART_DELAY_SECONDS,
    max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES,
    min_stable_run_seconds: float = MIN_STABLE_RUN_SECONDS,
    stop_event: Event | None = None,
) -> None:
    """command를 자식 프로세스로 띄우고, 비정상 종료하면 재시작한다.

    classify_exit(exit_code)가 문자열을 반환하면 "재시도해도 안 풀리는
    상황"으로 보고 그 문자열을 사유로 로그에 남긴 뒤 멈춘다(정상 종료, 인자
    오류, 이미 실행 중 등 호출부가 아는 특수 케이스). None을 반환하면
    크래시로 보고, min_stable_run_seconds도 못 버틴 실패가
    max_consecutive_failures번 연속되면 크래시 루프로 판단해 포기한다.

    stop_event가 주어지고 밖에서 set되면(예: desktop이 창을 닫을 때), 지금
    떠 있는 자식 프로세스를 종료시키고 더 재시작하지 않고 바로 리턴한다.
    stop_event를 안 주면 내부적으로 아무도 안 건드리는 Event를 만들어 쓴다
    (recorder처럼 "이 프로세스가 끝날 때까지" 영원히 감시하는 경우).
    """
    stop_event = stop_event if stop_event is not None else Event()
    consecutive_failures = 0

    while not stop_event.is_set():
        logger.info("%s를 시작합니다", command)
        started_at = time.monotonic()
        process = subprocess.Popen(command)

        while process.poll() is None:
            if stop_event.wait(timeout=0.2):
                logger.info("중지 요청을 받아 %s를 종료합니다", command)
                process.terminate()
                process.wait(timeout=5)
                return

        exit_code = process.returncode
        ran_for_seconds = time.monotonic() - started_at

        stop_reason = classify_exit(exit_code)
        if stop_reason is not None:
            logger.info("%s (exit code %d). 재시작하지 않고 멈춥니다.", stop_reason, exit_code)
            return

        if ran_for_seconds >= min_stable_run_seconds:
            consecutive_failures = 0
        else:
            consecutive_failures += 1

        if consecutive_failures >= max_consecutive_failures:
            logger.error(
                "%s가 %s초도 못 버티고 연속 %d번 비정상 종료했습니다"
                " (exit code %d). 같은 문제가 반복되는 것으로 보여 재시작을 멈춥니다.",
                command,
                min_stable_run_seconds,
                consecutive_failures,
                exit_code,
            )
            return

        logger.warning(
            "%s가 비정상 종료했습니다 (exit code %d, 연속 실패 %d/%d). %s초 후 재시작합니다.",
            command,
            exit_code,
            consecutive_failures,
            max_consecutive_failures,
            restart_delay_seconds,
        )
        if stop_event.wait(timeout=restart_delay_seconds):
            logger.info("중지 요청을 받아 재시작을 멈춥니다.")
            return
