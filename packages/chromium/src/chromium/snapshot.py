"""브라우저가 쓰는 중인 SQLite 파일(History, Favicons)을 안전하게 읽기 위한 복사본 도구.

브라우저는 이 파일들을 열어 둔 채 계속 쓴다. 원본을 직접 열면 브라우저를 방해하거나 잠금에 걸리고,
파일만 복사하면 쓰는 도중의 어중간한 상태(WAL 모드면 `-wal`에만 있는 최근 기록 포함)를 가져올 수
있다. 그래서 SQLite backup API로 한 번에 일관된 복사본을 만들고(실패하면 파일 복사로 대신),
복사본은 임시 작업 폴더에 둔다. 복사본에는 방문한 페이지의 주소가 들어 있어서, 작업 폴더는
프로세스별로 따로 만들고 쓰고 나면 바로 지우며, 비정상 종료로 남은 것은 다음 시작 때 지운다.

recorder(방문 기록)와 hub(아이콘)가 같은 규칙을 쓰도록 이 패키지에 둔다.
"""

import contextlib
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

import psutil

# 원본의 "바뀌었는지" 비교에 쓰는 보조 파일. WAL 모드에서는 새 기록이 한동안 -wal에만 있어서,
# 본 파일의 mtime/size만 보면 변경을 놓친다.
_WAL_SUFFIX = "-wal"

Fingerprint = tuple[tuple[int, int], tuple[int, int] | None]


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def fingerprint(source: Path) -> Fingerprint | None:
    """원본이 바뀌었는지 비교하는 값(본 파일 + 있으면 -wal의 mtime/size). 파일이 없으면 None."""
    main = _stat_key(source)
    if main is None:
        return None
    return main, _stat_key(source.with_name(source.name + _WAL_SUFFIX))


# sqlite3 상수: 원본이 다른 연결에 잠겨 있을 때 backup 한 단계가 돌려주는 상태.
_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6


def _abort_if_locked(status: int, remaining: int, total: int) -> None:
    """backup 진행 콜백: 원본이 잠겨 있으면 중단한다.

    backup()은 잠겨 있으면 기본적으로 풀릴 때까지 0.25초씩 쉬며 **무한히** 다시 시도한다. 브라우저가
    계속 잠가 두는 파일(지금 쓰는 프로필)에서는 영영 안 끝나서 hub 요청이나 recorder의 틱 루프가
    멈춘다. 예외를 던지면 backup이 중단되고 sqlite3.Error로 올라가 호출부가 파일 복사로 넘어간다.
    """
    if status in (_SQLITE_BUSY, _SQLITE_LOCKED):
        raise sqlite3.OperationalError("source database is locked")


def open_readonly(path: Path, timeout: float = 5.0) -> sqlite3.Connection:
    """SQLite 파일을 읽기 전용으로 연다(호출부가 contextlib.closing으로 닫는다).

    경로를 file: URI로 만들 때 직접 이어 붙이면 "#"(이후가 잘려 mode=ro가 사라진다)나 "%41" 같은
    문자열(디코딩되어 다른 경로가 된다)이 든 사용자 폴더에서 엉뚱한 파일을 열거나 실패한다 —
    Path.as_uri()가 이런 문자를 인코딩한다. recorder·hub 어디서든 이 함수로 연다.
    """
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=timeout)


def snapshot_database(source: Path, target: Path) -> bool:
    """source를 target에 복사한다. 성공하면 True.

    SQLite backup API는 원본을 한 번의 읽기로 복사해서 복사본이 하나의 일관된 상태가 된다. 브라우저가
    지금 쓰는 중인 프로필의 파일은 브라우저가 잠가 두어(배타적 잠금) backup이 안 된다 — 이때는 기다리지
    않고(아래 _abort_if_locked) 바로 파일 복사로 대신한다(쓰는 도중이면 덜 일관될 수 있다). 둘 다
    안 되면 반쯤 만들어진 target을 지우고 False — 호출부가 부분 복사본을 쓰지 않게 한다.
    """
    try:
        with (
            contextlib.closing(open_readonly(source, timeout=0.1)) as src,
            contextlib.closing(sqlite3.connect(target)) as dst,
        ):
            src.backup(dst, progress=_abort_if_locked)
        return True
    except sqlite3.Error:
        pass
    try:
        shutil.copyfile(source, target)
        return True
    except OSError:
        target.unlink(missing_ok=True)
        return False


_PID_PART = re.compile(r"(\d+)-")


def create_work_dir(prefix: str) -> Path:
    """복사본을 둘 임시 작업 폴더를 만든다. 이름에 이 프로세스의 pid를 넣는다.

    pid가 들어 있어야 remove_stale_work_dirs가 "아직 살아 있는 프로세스의 폴더"를 알아본다 —
    --db-path가 다른 recorder나 포트가 다른 hub처럼 동시에 뜬 다른 프로세스의 폴더를 지우지
    않으려는 것이다.
    """
    return Path(tempfile.mkdtemp(prefix=f"{prefix}{os.getpid()}-"))


def remove_stale_work_dirs(prefix: str) -> None:
    """비정상 종료로 남은 작업 폴더를 지운다. 프로세스를 시작할 때, 작업 폴더를 만들기 전에 한 번 부른다.

    prefix로 시작하는 폴더 중 pid가 없는 옛 형식이거나, 그 pid의 프로세스가 이미 없거나, 이
    프로세스 자신의 pid(시작 전이라 이전 실행이 남긴 것)인 것을 지운다. 다른 살아 있는
    프로세스의 폴더는 건드리지 않는다.
    """
    for folder in Path(tempfile.gettempdir()).glob(f"{prefix}*"):
        match = _PID_PART.match(folder.name[len(prefix) :])
        if match is not None:
            pid = int(match.group(1))
            if pid != os.getpid() and psutil.pid_exists(pid):
                continue
        shutil.rmtree(folder, ignore_errors=True)
