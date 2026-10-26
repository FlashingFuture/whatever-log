"""recorder가 실제로 돌면서 기록하고 있는지 확인한다.

lock 상태만 보면 "프로세스가 떠 있다"까지만 알 수 있고, 뭔가에 걸려서 멈춘
채로 틱이 하나도 안 쌓이는 상황은 못 잡는다. lock 상태 + 최근 틱 시각을 같이
봐야 "진짜로 돌고 있다"를 확인할 수 있다.

사용법:
    python -m recorder.healthcheck
    python -m recorder.healthcheck --db-path ... --expected-interval 15
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from recorder.__main__ import DEFAULT_DB_PATH, DEFAULT_INTERVAL_SECONDS, _lock_path_for_db
from recorder.lock import AlreadyRunningError, acquire_lock

# 틱이 이 배수(interval 기준)만큼 안 들어오면 "멈춘 것"으로 본다. 체크 시점이
# 다음 샘플링 직전일 수도 있어서 1배보다는 여유를 둔다.
STALE_MULTIPLIER = 3


def check(db_path: Path, expected_interval: float) -> tuple[bool, str]:
    """(건강한지, 사람이 읽을 메시지)를 반환한다."""
    lock_path = _lock_path_for_db(db_path)
    try:
        lock = acquire_lock(lock_path)
    except AlreadyRunningError:
        pass  # 실행 중 — 아래에서 최근 틱도 확인한다
    else:
        lock.release()
        return False, f"recorder가 실행 중이지 않습니다 (lock: {lock_path})."

    if not db_path.exists():
        return False, f"실행 중이지만 DB 파일이 아직 없습니다: {db_path}"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT sampled_at FROM ticks ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()

    if row is None:
        return False, "실행 중이지만 아직 기록된 틱이 없습니다."

    last_tick = datetime.fromisoformat(row[0])
    elapsed = (datetime.now(UTC) - last_tick).total_seconds()
    threshold = expected_interval * STALE_MULTIPLIER

    if elapsed > threshold:
        return False, (
            f"실행 중이지만 마지막 틱이 {elapsed:.0f}초 전입니다 "
            f"(기대 interval {expected_interval:.0f}초의 {STALE_MULTIPLIER}배인 "
            f"{threshold:.0f}초를 넘었습니다 — 멈춘 것으로 보입니다)."
        )

    return True, f"정상 — 마지막 틱 {elapsed:.0f}초 전 ({last_tick.isoformat()})."


def main() -> None:
    if sys.platform == "win32" and sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="recorder 헬스체크")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--expected-interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="recorder를 실행할 때 준 --interval과 맞춰주세요.",
    )
    args = parser.parse_args()

    healthy, message = check(args.db_path, args.expected_interval)
    print(message)
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
