"""개발용 저장소(clone)에 쌓인 기록·목표를 설치한 번들의 데이터 폴더로 **복사**한다.

개발 폴더는 DB를 앱 폴더 안(`apps/recorder/recorder.db` 등)에 두고, 번들은 `%LOCALAPPDATA%\\whatever.log`에 둔다(`common.paths`). 두 위치는 자동으로 이어지지 않아서,
개발하던 PC에 번들을 설치해 일상 용도로 쓰려면 한 번 옮겨야 한다.

- **원본은 건드리지 않는다.** 읽기 전용으로 열어 SQLite의 백업 API로 복사한다 — 원본을 쓰는 기록기가 떠 있어도(WAL의 아직 합치지 않은 변경까지 포함해서) 일관된 복사본이 나온다.
  파일을 그대로 복사하면 `-wal`·`-shm`을 빠뜨려 최근 기록을 잃거나 깨진 DB가 된다.
- **복사본은 임시 파일에 먼저 만들고 검사한 뒤 바꿔 넣는다.** 도중에 실패해도 데이터 폴더에는 반쯤 쓴 파일이 남지 않는다.
- **이미 있는 데이터를 덮어쓰지 않는다.** 대상 파일이 있으면 거절하고, `replace=True`면 이전 파일을 `<이름>.before-import`로 옮겨 둔 뒤 넣는다.
- **번들의 구성 요소가 떠 있으면 거절한다.** 쓰는 중인 DB 파일을 바꿔 끼우면 안 된다.
- 로그인 정보는 Windows 자격 증명 관리자(같은 사용자의 모든 설치가 공유)에 있어서 옮길 것이 없다. 기기 ID(`sync.db`·`goals.db`)는 같은 PC라 그대로 가져간다 —
  그래서 **옮긴 뒤에는 개발 폴더의 기록기·동기화 에이전트를 끈다**(같은 기기 ID로 두 곳이 올리면 서로의 값을 덮어쓴다). `install`이 이전 폴더의 프로세스를 끄고 자동 시작을 바꿔 준다.
"""

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from common import paths

from launcher import components

#: 개발용 저장소 안의 위치(원본) → 데이터 폴더 안의 이름(대상). 동기화 상태(sync.db)는 없을 수 있다.
SOURCES = (
    ("apps/recorder/recorder.db", "recorder.db", "기록"),
    ("apps/hub/goals.db", "goals.db", "목표"),
    ("apps/sync/sync.db", "sync.db", "동기화 상태"),
)

#: 복사한 뒤 사용자에게 보여 줄 개수(있는 표만). 열 수 없거나 표가 없으면 건너뛴다.
_COUNTS = {"recorder.db": ("ticks", "기록한 시점"), "goals.db": ("goals", "목표")}


class ImportRefused(Exception):
    """복사를 시작하기 전에 거절하는 사유. 메시지는 사용자에게 그대로 보여 줄 수 있다."""


@dataclass(frozen=True)
class Planned:
    """복사할 파일 하나: 원본, 대상, 사용자용 이름."""

    source: Path
    target: Path
    label: str


def plan(repo_root: Path, data_folder: Path) -> list[Planned]:
    """repo_root(개발용 저장소 폴더)에서 복사할 것들. 원본이 없는 항목은 뺀다(동기화를 한 적 없으면 sync.db가 없다). 아무것도 없으면 ImportRefused."""
    if not repo_root.is_dir():
        raise ImportRefused(f"폴더가 없어요: {repo_root}")
    found = [Planned(repo_root / relative, data_folder / name, label) for relative, name, label in SOURCES if (repo_root / relative).is_file()]
    if not any(item.target.name == "recorder.db" or item.target.name == "goals.db" for item in found):
        raise ImportRefused(f"{repo_root} 안에서 기록(apps/recorder/recorder.db)이나 목표(apps/hub/goals.db)를 찾지 못했어요. 개발용 저장소 폴더가 맞나요?")
    return found


def check_ready(items: list[Planned], *, replace: bool) -> None:
    """복사해도 안전한지 확인한다. 안전하지 않으면 ImportRefused(아무것도 바꾸지 않은 상태다)."""
    running = [component.label for component in components.COMPONENTS if components.state(component) != components.STOPPED]
    # 화면(창)과 그 안의 hub도 DB를 연다(`stop`은 열린 창을 닫지 않는다). hub는 요청마다 goals.db를 열고 닫으므로 떠 있으면 교체 중에 쓸 수 있다.
    running += [label for label, module in (("화면(창)", "desktop"), ("hub", "hub")) if components.find_processes(module)]
    if running:
        raise ImportRefused(f"{', '.join(running)}이(가) 실행 중이에요. 쓰는 중인 데이터를 바꿔 끼울 수 없으니 먼저 `whatever-log stop`을 실행하고 열려 있는 창을 닫아 주세요.")
    existing = [item.target.name for item in items if item.target.exists()]
    if existing and not replace:
        raise ImportRefused(
            f"이미 데이터가 있어요: {', '.join(existing)}. 덮어쓰지 않았어요. 기존 것을 `<이름>.before-import`로 옮기고 가져오려면 --replace를 붙여 주세요."
        )


def _backup(source: Path, destination: Path, *, verify: bool = True) -> None:
    """source를 읽기 전용으로 열어 SQLite 백업 API로 destination에 복사한다(WAL에만 있는 커밋된 변경도 포함). verify면 복사본을 검사한다."""
    origin = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        copy = sqlite3.connect(destination)
        try:
            origin.backup(copy)
            if verify and copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("복사본 검사에 실패했어요")
        finally:
            copy.close()
    finally:
        origin.close()


def _prepare_copy(source: Path, target: Path) -> Path:
    """source의 검사를 마친 복사본을 target 옆 임시 파일로 만들어 돌려준다. 실패하면 임시 파일을 지우고 예외를 그대로 낸다(target은 건드리지 않는다)."""
    temporary = target.with_name(target.name + ".importing")
    temporary.unlink(missing_ok=True)
    try:
        _backup(source, temporary)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _keep_previous(target: Path, aside: Path) -> None:
    """기존 target을 aside에 보존한다. 커밋된 변경이 -wal에만 남아 있을 수 있어(비정상 종료 뒤) 백업 API로 합쳐서 보존한다.
    SQLite로 열 수 없는 파일이면(손상) 파일 그대로 복사한다 — 어느 쪽이든 target은 그대로 둔다."""
    aside.unlink(missing_ok=True)
    try:
        _backup(target, aside, verify=False)
    except sqlite3.Error:
        aside.unlink(missing_ok=True)
        shutil.copy2(target, aside)


def _install_copy(temporary: Path, target: Path) -> None:
    """검사를 마친 복사본을 target 자리에 넣는다. 이미 있던 target은 먼저 `<이름>.before-import`에 보존하고, 넣다가 실패하면 되돌린다."""
    aside = target.with_name(target.name + ".before-import")
    had_previous = target.exists()
    try:
        if had_previous:
            _keep_previous(target, aside)
        for suffix in ("-wal", "-shm"):  # 옛 파일의 잔재가 새 DB에 섞이지 않게(이미 aside에 합쳐 보존했다)
            target.with_name(target.name + suffix).unlink(missing_ok=True)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        if had_previous and aside.exists():
            shutil.copy2(aside, target)  # 합쳐서 보존한 이전 내용으로 되돌린다
        raise


def _count(path: Path, table: str) -> int | None:
    """표의 행 수(없거나 읽지 못하면 None)."""
    try:
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return None


def run(repo_root: Path, say, *, dry_run: bool = False, replace: bool = False) -> bool:
    """개발용 저장소의 기록·목표를 데이터 폴더로 복사한다. 잘 됐으면 True. 거절·실패하면 사유를 알리고 False(원본은 어느 경우에도 그대로다)."""
    folder = paths.data_dir()
    if folder is None:
        say("문제: 이 폴더는 개발용 저장소라 데이터가 이미 앱 폴더 안에 있어요. 설치한 번들 폴더에서 실행해 주세요.")
        return False
    prefix = "[미리보기] " if dry_run else ""
    try:
        items = plan(repo_root, folder)
        check_ready(items, replace=replace)
    except ImportRefused as refusal:
        say(f"문제: {refusal}")
        return False

    say(f"{prefix}{repo_root} → {folder}")
    if dry_run:
        for item in items:
            say(f"{prefix}{item.label}: {item.source.name}({item.source.stat().st_size // 1024:,}KB)을 복사합니다{' (기존 파일은 .before-import로 옮김)' if item.target.exists() else ''}.")
        return True

    folder.mkdir(parents=True, exist_ok=True)
    failed = False
    for item in items:
        try:
            _install_copy(_prepare_copy(item.source, item.target), item.target)
        except (sqlite3.Error, OSError) as error:
            failed = True
            say(f"문제: {item.label}({item.source.name})을 복사하지 못했어요: {error}")
            continue
        counted = _COUNTS.get(item.target.name)
        count = _count(item.target, counted[0]) if counted else None
        say(f"{item.label}: 복사했어요" + (f" ({counted[1]} {count:,}개)" if counted and count is not None else "") + ".")
    if failed:
        return False
    say("끝났어요. 개발 폴더의 기록기·동기화 에이전트는 끄세요(같은 기기 ID로 두 곳이 올리면 서로 덮어써요). `whatever-log install`이 이전 폴더의 프로세스를 끄고 자동 시작을 바꿔 줘요.")
    return True
