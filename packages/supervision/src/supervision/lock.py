"""프로세스가 중복 실행되는 걸 막는 lock file.

원래 recorder 전용으로 있었다(apps/recorder) — 자동 시작 + supervisor
재시작을 쓰면 두 인스턴스가 동시에 뜨는 상황이 생길 수 있다(예: 로그인
트리거와 supervisor 재시작이 겹침). hub도 포트를 두 번 바인딩하려다
혼란스러운 에러로 죽는 것보다, 같은 방식으로 "이미 실행 중"을 명확히
감지하는 게 나아서 공통 모듈로 뺐다.

PID 파일을 직접 구현하는 대신 OS 레벨 파일 잠금(filelock)을 쓴다 — 프로세스가
죽으면 OS가 자동으로 잠금을 풀어줘서, "죽은 프로세스가 남긴 stale lock"을 따로
감지/정리할 필요가 없다.
"""

from pathlib import Path

from filelock import FileLock, Timeout


class AlreadyRunningError(RuntimeError):
    """다른 인스턴스가 이미 이 lock을 잡고 있다.

    일반 RuntimeError가 아니라 전용 타입으로 둔 이유: NotImplementedError나
    RecursionError도 RuntimeError의 서브클래스라서, 호출부가 그냥
    `except RuntimeError`로 잡으면 전혀 다른 원인의 오류까지 "이미 실행 중"으로
    오인하게 된다. 호출부는 이 타입만 구체적으로 잡아서 처리해야 한다.
    """


def acquire_lock(path: Path) -> FileLock:
    """다른 인스턴스가 이미 실행 중이면 기다리지 않고 바로 실패한다."""
    lock = FileLock(path)
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise AlreadyRunningError(
            f"이미 다른 인스턴스가 실행 중인 것 같습니다 (lock: {path}). "
            "중복 실행을 막기 위해 시작하지 않습니다."
        ) from exc
    return lock
