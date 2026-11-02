"""프로세스 이름에 대응하는 실행 파일 경로를 찾는다.

아이콘(apps/hub)을 보여주려면 이름만으로는 부족하고 exe 경로가 필요하다. 틱마다
모든 창 프로세스의 경로를 조회하면 psutil 호출이 창 수만큼 더 늘어나므로, 기록
루프(__main__)가 "이번 실행에서 처음 본 이름"에 대해서만 이 함수를 부른다 — 한 번
훑어서 필요한 이름들을 한꺼번에 해결한다.

경로를 못 구하는 프로세스(관리자 권한으로 뜬 것 등)는 결과에서 빠진다. 그런
프로세스는 아이콘이 없는 채로 두고(UI가 대체 표시) 재시도하지 않는다.
"""

import logging
import sqlite3
from collections import Counter
from collections.abc import Callable, Collection

import psutil

from recorder.storage import save_process_paths

logger = logging.getLogger("recorder")


def resolve_exe_paths(names: Collection[str]) -> dict[str, str]:
    """names에 해당하는 프로세스의 exe 경로를 {이름: 경로}로 돌려준다.

    같은 이름의 프로세스가 여럿이면 먼저 만난 것의 경로를 쓴다(같은 이름은 보통
    같은 실행 파일이다). 이름 비교는 정확히 일치해야 한다 — processes 테이블에
    저장된 이름 그대로 조회한다.
    """
    wanted = set(names)
    found: dict[str, str] = {}
    if not wanted:
        return found

    for process in psutil.process_iter(["name", "exe"]):
        name = process.info["name"]
        exe = process.info["exe"]
        # AccessDenied인 속성은 process_iter가 None으로 채운다.
        if name in wanted and exe and name not in found:
            found[name] = exe
            if len(found) == len(wanted):
                break
    return found


class ProcessPathTracker:
    """이번 실행에서 경로 조회를 끝낸 이름을 기억해, 처음 본 이름만 조회·기록한다.

    조회가 성공했으면(경로를 못 구한 이름 포함 — 닫힌 프로세스는 다시 봐도 같다)
    그 이름은 끝난 것으로 본다. 조회나 기록이 예외로 실패하면 일시적인 문제(SQLite
    잠금, psutil 오류)일 수 있어서 다음 틱에 다시 시도하되, max_attempts번 연속
    실패하면 포기한다 — 계속 실패하는 문제에서 매 틱 프로세스를 훑지 않게.

    부가 정보라서, 실패해도 예외를 밖으로 내보내 틱 기록을 멈추지 않는다.
    """

    def __init__(
        self,
        resolve: Callable[[Collection[str]], dict[str, str]] = resolve_exe_paths,
        save: Callable[[sqlite3.Connection, dict[str, str]], None] = save_process_paths,
        max_attempts: int = 3,
    ) -> None:
        self._resolve = resolve
        self._save = save
        self._max_attempts = max_attempts
        self._done: set[str] = set()
        self._failures: Counter[str] = Counter()

    def record_new(self, conn: sqlite3.Connection, names: Collection[str]) -> None:
        new_names = set(names) - self._done
        if not new_names:
            return
        try:
            self._save(conn, self._resolve(new_names))
        except Exception:
            logger.warning("프로세스 경로를 기록하지 못했습니다.", exc_info=True)
            for name in new_names:
                self._failures[name] += 1
                if self._failures[name] >= self._max_attempts:
                    self._done.add(name)
            return
        self._done |= new_names
