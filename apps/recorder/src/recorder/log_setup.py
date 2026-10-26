"""recorder와 supervisor가 공통으로 쓰는 파일 로깅 설정.

둘 다 pythonw.exe(콘솔 없음)로 백그라운드 상시 실행되는 전제라, 같은 방식으로
로그를 남겨야 한다 — 그래야 "recorder가 왜 죽었는지"와 "supervisor가 왜
재시작했는지"를 같은 포맷으로 추적할 수 있다. 두 프로세스는 별개 OS 프로세스라
RotatingFileHandler를 같은 파일에 공유하면 롤오버 시점에 서로 부딪힐 수 있으니,
로거 이름뿐 아니라 로그 파일도 각자 둔다(__main__.py는 recorder.log,
supervisor.py는 supervisor.log).
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
