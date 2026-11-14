"""알림 에이전트를 자식 프로세스로 띄우고, 비정상 종료하면 다시 띄운다.

sync_agent.supervisor와 같은 모양이다(공통 루프는 packages/supervision). 여기에 더해 박동 감시를 켠다 — 에이전트가 뜬 채로 멈춰도(프로세스가 끝나지 않아도) 다시 띄운다. 로그인 시 자동으로 뜨도록 등록할 대상은 에이전트 자신이 아니라 이
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
from supervision.heartbeat import Heartbeat
from supervision.log_setup import configure_logging
from supervision.supervisor import supervise

_APP_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = data_path(_APP_DIR, "notifier-supervisor.log", subdir="logs")
#: 에이전트가 주기마다 `beat()`로 갱신하는 박동 파일. `whatever-log status`가 읽어 "마지막 확인"을 보여 준다.
HEARTBEAT_PATH = data_path(_APP_DIR, "notifier.heartbeat")

#: 에이전트의 기본 확인 주기(초). `notifier.__main__.DEFAULT_INTERVAL_SECONDS`와 같아야 한다(시험이 확인한다) — supervisor는 가볍게 유지하려고 에이전트
#: 모듈(집계·목표 패키지를 불러온다)을 불러오지 않아서 값을 따로 둔다.
AGENT_DEFAULT_INTERVAL_SECONDS = 60.0
#: 박동이 끊겨도 기다려 주는 시간 = 주기의 이 배수(최소 MIN_STALE_SECONDS). 한 번의 확인이 기록 DB 잠금(5초)·토스트(최대 20초)로 길어져도 넉넉하다.
STALE_INTERVALS = 5
MIN_STALE_SECONDS = 180.0
#: 첫 박동까지 기다려 주는 시간(시작해서 모듈을 불러오는 동안).
STARTUP_GRACE_SECONDS = 120.0

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


def _interval_from(argv: list[str]) -> float:
    """에이전트에 넘길 인자에서 `--interval`(초)을 읽는다. 없거나 읽을 수 없으면 기본 주기 — 값이 틀렸다면 에이전트가 인자 오류로 스스로 끝난다."""
    for index, argument in enumerate(argv):
        value = None
        if argument == "--interval" and index + 1 < len(argv):
            value = argv[index + 1]
        elif argument.startswith("--interval="):
            value = argument.partition("=")[2]
        if value is not None:
            try:
                parsed = float(value)
            except ValueError:
                break
            if parsed > 0 and parsed != float("inf"):
                return parsed
            break
    return AGENT_DEFAULT_INTERVAL_SECONDS


def heartbeat_for(argv: list[str]) -> Heartbeat:
    """에이전트의 주기에 맞춘 박동 감시 설정. 주기가 길수록 박동 간격도 길어지므로 허용 시간을 주기에 비례해 늘린다."""
    interval = _interval_from(argv)
    return Heartbeat(
        path=HEARTBEAT_PATH,
        stale_after_seconds=max(MIN_STALE_SECONDS, interval * STALE_INTERVALS),
        startup_grace_seconds=STARTUP_GRACE_SECONDS,
    )


def main() -> None:
    """알림 에이전트를 실행하고, 비정상 종료나 멈춤(박동 끊김)이면 잠깐 쉬었다가 재시작한다(supervise() 위임)."""
    configure_logging(logger, DEFAULT_LOG_PATH)
    keep_trimmed()  # 쉬는 시간이 긴 백그라운드 프로세스 — 안 쓰는 물리 메모리를 돌려준다(common.memory)
    supervise(
        [sys.executable, "-m", "notifier", *sys.argv[1:]],
        logger=logger,
        classify_exit=_classify_exit,
        heartbeat=heartbeat_for(sys.argv[1:]),
    )


if __name__ == "__main__":
    main()
