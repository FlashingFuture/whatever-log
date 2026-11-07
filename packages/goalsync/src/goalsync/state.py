"""동기화 에이전트의 자기 상태(`sync.db`): 이 기기의 ID와, 서버에 마지막으로 보낸 달성 분.

`goals.db`는 사용자 설정이라 hub도 쓰지만, 이 상태는 에이전트만 쓴다 — 쓰기 주체를 나눠 두려고 파일을 따로 둔다.
기기 ID는 처음 만들 때 정한 무작위 UUID이고 하드웨어 값(MAC, PC 이름)이 아니다(docs/data-handling.md).
"""

import sqlite3
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS device (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    device_id TEXT NOT NULL
);
-- 서버에 마지막으로 보낸 (서버 목표, 날짜)의 값. 같은 값은 다시 보내지 않는다.
CREATE TABLE IF NOT EXISTS pushed (
    remote_id TEXT NOT NULL,
    day TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    target_minutes INTEGER NOT NULL,
    PRIMARY KEY (remote_id, day)
);
"""


def peek_device_id(path: Path) -> str | None:
    """sync.db에 이미 있는 이 기기의 ID. 파일이나 값이 없으면 None — 읽기 전용으로 열어서 hub가 에이전트의 파일을 만들거나 바꾸지 않는다."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT device_id FROM device WHERE id = 1").fetchone()
    except sqlite3.Error:  # 파일이 없거나 아직 스키마가 없다
        return None
    finally:
        conn.close()
    return row[0] if row else None


class SyncState:
    """sync.db를 연다. 쓰고 나면 close()(또는 with)로 닫는다."""

    def __init__(self, path: Path) -> None:
        """path의 sync.db를 열고(없으면 만들고) 스키마를 준비한다."""
        self._conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(_SCHEMA)
        except BaseException:
            self._conn.close()
            raise

    def close(self) -> None:
        """연결을 닫는다."""
        self._conn.close()

    def __enter__(self) -> "SyncState":
        """with 문 진입 — 자신을 돌려준다."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """with 문을 나갈 때 닫는다."""
        self.close()

    def device_id(self) -> str:
        """이 기기의 ID. 처음 부르면 무작위 UUID를 만들어 저장한다."""
        row = self._conn.execute("SELECT device_id FROM device WHERE id = 1").fetchone()
        if row:
            return row[0]
        created = str(uuid.uuid4())
        self._conn.execute("INSERT OR IGNORE INTO device (id, device_id) VALUES (1, ?)", (created,))
        return self._conn.execute("SELECT device_id FROM device WHERE id = 1").fetchone()[0]

    def pushed(self, remote_id: str, day: str) -> tuple[int, int] | None:
        """서버에 마지막으로 보낸 (분, 목표 분). 보낸 적이 없으면 None."""
        row = self._conn.execute(
            "SELECT minutes, target_minutes FROM pushed WHERE remote_id = ? AND day = ?", (remote_id, day)
        ).fetchone()
        return (row[0], row[1]) if row else None

    def record_pushed(self, remote_id: str, day: str, minutes: int, target_minutes: int) -> None:
        """서버에 보낸 값을 기록한다."""
        self._conn.execute(
            "INSERT INTO pushed (remote_id, day, minutes, target_minutes) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(remote_id, day) DO UPDATE SET minutes = excluded.minutes, "
            "target_minutes = excluded.target_minutes",
            (remote_id, day, minutes, target_minutes),
        )

    def has_pushed_any(self, remote_id: str) -> bool:
        """이 서버 목표의 달성도를 한 번이라도 보냈는지(처음이면 더 긴 기간을 보낸다)."""
        return (
            self._conn.execute("SELECT 1 FROM pushed WHERE remote_id = ? LIMIT 1", (remote_id,)).fetchone() is not None
        )

    def forget(self, remote_id: str) -> None:
        """이 서버 목표에 보낸 기록을 지운다(연결이 끊겼을 때)."""
        self._conn.execute("DELETE FROM pushed WHERE remote_id = ?", (remote_id,))

    def forget_all(self) -> None:
        """보낸 기록을 모두 지운다(계정이 바뀌었을 때)."""
        self._conn.execute("DELETE FROM pushed")
