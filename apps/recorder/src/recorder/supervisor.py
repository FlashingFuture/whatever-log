"""recorder 워커를 자식 프로세스로 띄우고, 비정상 종료하면 다시 띄운다.

ActivityWatch의 aw-qt가 aw-watcher-window/aw-watcher-afk를 감시하는 것과 같은
패턴이다(docs/recorder-sqlite-design.md "나중에 고려할 것" 참고). Windows
서비스는 쓰지 않는다 — 서비스는 Session 0에 격리돼서 recorder가 필요로 하는
사용자 데스크톱(GetForegroundWindow 등)에 접근할 수 없다. 대신 이 supervisor를
로그인 시 실행되게 등록하고(Registry Run 키 또는 시작 폴더), 크래시 복구는 여기
직접 구현한다.

recorder.__main__과 같은 방식(log_setup.configure_logging)으로 로그를 남긴다 —
둘 다 pythonw.exe로 콘솔 없이 실행되는 전제라서, "recorder가 왜 죽었는지"뿐
아니라 "supervisor가 왜/언제 재시작했는지"도 추적할 수 있어야 한다. 같은 파일을
두 프로세스가 공유하면 로테이션 시점에 부딪힐 수 있어 로그 파일은 따로 둔다
(recorder.log / supervisor.log).

사용법: python -m recorder.supervisor --interval 15
(recorder.__main__이 받는 인자를 그대로 전달한다)
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

from recorder.__main__ import EXIT_ALREADY_RUNNING
from recorder.log_setup import configure_logging

RESTART_DELAY_SECONDS = 5.0

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "supervisor.log"

logger = logging.getLogger("recorder.supervisor")


def main() -> None:
    """recorder를 실행하고, 비정상 종료(exit code != 0)면 잠깐 쉬었다가 재시작한다.

    정상 종료(exit 0 — 사용자가 Ctrl+C로 끈 경우 등)면 재시작하지 않고 끝낸다.
    EXIT_ALREADY_RUNNING(다른 recorder가 이미 lock을 잡고 있음)도 재시작하지
    않는다 — 크래시가 아니라서 재시도해도 안 풀리고, 계속 재시도하면 로그만
    계속 쌓인다.
    """
    configure_logging(logger, DEFAULT_LOG_PATH)
    args = sys.argv[1:]

    while True:
        logger.info("recorder를 시작합니다 (args=%s)", args)
        result = subprocess.run([sys.executable, "-m", "recorder", *args])

        if result.returncode == 0:
            logger.info("recorder가 정상 종료했습니다. supervisor를 끝냅니다.")
            break
        if result.returncode == EXIT_ALREADY_RUNNING:
            logger.info(
                "다른 recorder가 이미 실행 중입니다. 재시작하지 않고 supervisor를 끝냅니다."
            )
            break

        logger.warning(
            "recorder가 비정상 종료했습니다 (exit code %d). %s초 후 재시작합니다.",
            result.returncode,
            RESTART_DELAY_SECONDS,
        )
        time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    main()
