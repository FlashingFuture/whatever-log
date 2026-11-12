"""동기화 에이전트를 자식 프로세스로 띄우고, 비정상 종료하면 다시 띄운다.

recorder.supervisor와 같은 모양이다(공통 루프는 packages/supervision). 로그인 시 자동으로 뜨도록 등록할 대상은 에이전트 자신이
아니라 이 supervisor다 — pythonw.exe로 콘솔 없이 돌고, 에이전트가 죽으면 잠깐 쉬었다가 다시 띄운다. 로그인하지 않았거나 동기화를
켜지 않았어도 에이전트는 그냥 건너뛰며 돌기 때문에(서버를 부르지 않는다) 항상 떠 있어도 부담이 없다.

로그는 sync_agent 자신의 로그(sync.log)와 겹치지 않게 supervisor.log에 따로 남긴다.

사용법: python -m sync_agent.supervisor --interval 300   (에이전트가 받는 인자를 그대로 전달한다)
"""

import logging
import sys
from pathlib import Path

from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from common.memory import keep_trimmed
from common.paths import data_path
from supervision.log_setup import configure_logging
from supervision.supervisor import supervise

DEFAULT_LOG_PATH = data_path(Path(__file__).resolve().parents[2], "sync-supervisor.log", subdir="logs")

logger = logging.getLogger("sync_agent.supervisor")

#: 로그인 시 자동 시작(Registry Run 키)에 등록할 때 쓰는 값 이름
AUTOSTART_VALUE_NAME = "WhateverLogSync"


def _classify_exit(exit_code: int) -> str | None:
    """재시도해도 안 풀리는 종료 코드면 멈출 사유를, 크래시면 None을 돌려준다(recorder.supervisor와 같은 기준).

    정상 종료(0)·인자 오류·이미 실행 중(다른 에이전트가 lock을 잡음)은 다시 띄워도 소용이 없다. 그 외는 크래시로 보고
    supervise()가 재시도하되, 뜨자마자 계속 죽으면 포기한다.
    """
    if exit_code == 0:
        return "동기화 에이전트가 정상 종료했습니다"
    if exit_code == EXIT_ARGUMENT_ERROR:
        return "동기화 에이전트 인자가 잘못되었습니다"
    if exit_code == EXIT_ALREADY_RUNNING:
        return "다른 동기화 에이전트가 이미 실행 중입니다"
    return None


def main() -> None:
    """동기화 에이전트를 실행하고, 비정상 종료면 잠깐 쉬었다가 재시작한다(supervise() 위임)."""
    configure_logging(logger, DEFAULT_LOG_PATH)
    keep_trimmed()  # 쉬는 시간이 긴 백그라운드 프로세스 — 안 쓰는 물리 메모리를 돌려준다(common.memory)
    supervise(
        [sys.executable, "-m", "sync_agent", *sys.argv[1:]],
        logger=logger,
        classify_exit=_classify_exit,
    )


if __name__ == "__main__":
    main()
