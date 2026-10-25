"""recorder 워커를 자식 프로세스로 띄우고, 비정상 종료하면 다시 띄운다.

ActivityWatch의 aw-qt가 aw-watcher-window/aw-watcher-afk를 감시하는 것과 같은
패턴이다(docs/recorder-sqlite-design.md "나중에 고려할 것" 참고). Windows
서비스는 쓰지 않는다 — 서비스는 Session 0에 격리돼서 recorder가 필요로 하는
사용자 데스크톱(GetForegroundWindow 등)에 접근할 수 없다. 대신 이 supervisor를
로그인 시 실행되게 등록하고(Registry Run 키 또는 시작 폴더), 크래시 복구는 여기
직접 구현한다.

사용법: python -m recorder.supervisor --interval 15
(recorder.__main__이 받는 인자를 그대로 전달한다)
"""

import subprocess
import sys
import time

from recorder.__main__ import EXIT_ALREADY_RUNNING

RESTART_DELAY_SECONDS = 5.0


def main() -> None:
    """recorder를 실행하고, 비정상 종료(exit code != 0)면 잠깐 쉬었다가 재시작한다.

    정상 종료(exit 0 — 사용자가 Ctrl+C로 끈 경우 등)면 재시작하지 않고 끝낸다.
    EXIT_ALREADY_RUNNING(다른 recorder가 이미 lock을 잡고 있음)도 재시작하지
    않는다 — 크래시가 아니라서 재시도해도 안 풀리고, 계속 재시도하면 로그만
    계속 쌓인다.
    """
    args = sys.argv[1:]
    while True:
        result = subprocess.run([sys.executable, "-m", "recorder", *args])
        if result.returncode in (0, EXIT_ALREADY_RUNNING):
            break
        time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    main()
