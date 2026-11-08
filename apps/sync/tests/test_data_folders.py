"""배포 모양의 데이터 폴더는 처음 쓸 때 만들어져야 한다(경로를 정하는 common.paths는 폴더를 만들지 않는다).

여러 패키지(goals·goalsync·recorder·supervision)를 함께 쓰므로, 로컬 기능이 goalsync를 import하지 못하게 하는 격리 규칙에 걸리지 않는
동기화 에이전트의 테스트에 둔다.
"""

def test_the_places_that_write_create_their_missing_data_folder(tmp_path) -> None:
    import logging

    from goals import GoalStore
    from goalsync import SyncState
    from recorder.storage import open_db
    from supervision.lock import acquire_lock
    from supervision.log_setup import configure_logging

    deep = tmp_path / "a" / "b"
    with GoalStore(deep / "goals.db"):
        pass
    with SyncState(deep / "c" / "sync.db"):
        pass
    open_db(deep / "d" / "recorder.db").close()
    lock = acquire_lock(deep / "e" / "x.lock")
    lock.release()
    logger = logging.getLogger("paths-test")
    configure_logging(logger, deep / "logs" / "x.log")
    logger.handlers[0].close()
    logger.handlers.clear()

    for name in ("goals.db", "c/sync.db", "d/recorder.db", "logs/x.log"):
        assert (deep / name).exists(), name
    assert (deep / "e").is_dir()  # lock 파일은 놓으면 지워지므로 폴더만 확인한다
