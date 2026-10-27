"""콘솔 없이 백그라운드로 상시 실행되는 프로세스가 공통으로 쓰는 파일 로깅 설정.

원래 recorder 전용으로 있었다(apps/recorder) — recorder/supervisor처럼
pythonw.exe(콘솔 없음)로 백그라운드 상시 실행되는 프로세스는 print() 대신
파일 로그로만 상태를 남길 수 있는데, hub도 같은 처지라 공통 모듈로 뺐다.

서로 다른 프로세스가 RotatingFileHandler를 같은 파일에 공유하면 롤오버
시점에 부딪힐 수 있으니, 호출부마다 로거 이름뿐 아니라 로그 파일도 각자
둬야 한다(recorder.log / supervisor.log / hub.log 처럼).
"""

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


def configure_logging(logger: logging.Logger, log_path: Path) -> None:
    """logger에 로테이팅 파일 핸들러(+콘솔이 있으면 콘솔 핸들러도)를 붙인다.

    파일 핸들러는 항상 켜고, 콘솔(sys.stdout)이 없는 환경(pythonw.exe 등)이면
    콘솔 핸들러는 생략한다. 같은 프로세스에서 다시 불려도(테스트 등) 핸들러가
    안 쌓이게 매번 비우고 다시 붙인다.
    """
    logger.setLevel(logging.INFO)
    for old_handler in logger.handlers:
        old_handler.close()  # clear()만 하면 파일 핸들이 GC될 때까지 안 풀린다
    logger.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(stream_handler)
