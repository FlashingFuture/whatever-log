"""레코더가 중복 실행되는 걸 막는 lock file.

자동 시작 + supervisor 재시작을 쓰면 두 인스턴스가 동시에 뜨는 상황이 생길 수
있다(예: 로그인 트리거와 supervisor 재시작이 겹침). 같은 SQLite 파일에 두
프로세스가 동시에 쓰면 경쟁/중복 집계로 이어지므로 시작 시점에 막는다.

PID 파일을 직접 구현하는 대신 OS 레벨 파일 잠금(filelock)을 쓴다 — 프로세스가
죽으면 OS가 자동으로 잠금을 풀어줘서, "죽은 프로세스가 남긴 stale lock"을 따로
감지/정리할 필요가 없다 (docs/recorder-sqlite-design.md의 "나중에 고려할 것"에서
언급했던 문제).
"""

from pathlib import Path

from filelock import FileLock, Timeout


def acquire_lock(path: Path) -> FileLock:
    """다른 recorder가 이미 실행 중이면 기다리지 않고 바로 실패한다."""
    lock = FileLock(path)
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise RuntimeError(
            f"이미 recorder가 실행 중인 것 같습니다 (lock: {path}). "
            "중복 실행을 막기 위해 시작하지 않습니다."
        ) from exc
    return lock
