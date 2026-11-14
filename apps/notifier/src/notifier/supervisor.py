"""알림 에이전트를 자식 프로세스로 띄우고, 비정상 종료하면 다시 띄운다.

sync_agent.supervisor와 같은 모양이다(공통 루프는 packages/supervision). 로그인 시 자동으로 뜨도록 등록할 대상은 에이전트 자신이 아니라 이
supervisor다 — pythonw.exe로 콘솔 없이 돌고, 에이전트가 죽으면 잠깐 쉬었다가 다시 띄운다. 알림 규칙이 없으면 에이전트는 목표 DB만 가볍게 읽으며
돌기 때문에 항상 떠 있어도 부담이 없다.

로그는 notifier 자신의 로그(notifier.log)와 겹치지 않게 notifier-supervisor.log에 따로 남긴다.

사용법: python -m notifier.supervisor --interval 60   (에이전트가 받는 인자를 그대로 전달한다)
"""

import logging
import sys
from pathlib import Path

from common.exit_codes import EXIT_ALREADY_RUNNING, EXIT_ARGUMENT_ERROR
from common.memory import keep_trimmed
from common.paths import data_path
from supervision.log_setup import configure_logging
from supervision.supervisor import supervise

DEFAULT_LOG_PATH = data_path(Path(__file__).resolve().parents[2], "notifier-supervisor.log", subdir="logs")

logger = logging.getLogger("notifier.supervisor")

#: 로그인 시 자동 시작(Registry Run 키)에 등록할 때 쓰는 값 이름
AUTOSTART_VALUE_NAME = "WhateverLogNotifier"


def _classify_exit(exit_code: int) -> str | None:
    """재시도해도 안 풀리는 종료 코드면 멈출 사유를, 크래시면 None을 돌려준다(다른 supervisor와 같은 기준)."""
    if exit_code == 0:
        return "알림 에이전트가 정상 종료했습니다"
    if exit_code == EXIT_ARGUMENT_ERROR:
        return "알림 에이전트 인자가 잘못되었습니다"
    if exit_code == EXIT_ALREADY_RUNNING:
        return "다른 알림 에이전트가 이미 실행 중입니다"
    return None


def main() -> None:
    """알림 에이전트를 실행하고, 비정상 종료면 잠깐 쉬었다가 재시작한다(supervise() 위임)."""
    configure_logging(logger, DEFAULT_LOG_PATH)
    keep_trimmed()  # 쉬는 시간이 긴 백그라운드 프로세스 — 안 쓰는 물리 메모리를 돌려준다(common.memory)
    supervise(
        [sys.executable, "-m", "notifier", *sys.argv[1:]],
        logger=logger,
        classify_exit=_classify_exit,
    )


if __name__ == "__main__":
    main()
