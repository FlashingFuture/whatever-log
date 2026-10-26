"""recorder가 실제로 돌면서 기록하고 있는지 확인한다.

lock 상태만 보면 "프로세스가 떠 있다"까지만 알 수 있고, 뭔가에 걸려서 멈춘
채로 틱이 하나도 안 쌓이는 상황은 못 잡는다. lock 상태 + 최근 틱 시각을 같이
봐야 "진짜로 돌고 있다"를 확인할 수 있다.

사용법:
    python -m recorder.healthcheck
    python -m recorder.healthcheck --db-path ... --expected-interval 15
"""

import argparse
import math
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from recorder.__main__ import DEFAULT_DB_PATH, DEFAULT_INTERVAL_SECONDS, _lock_path_for_db
from recorder.lock import AlreadyRunningError, acquire_lock

# 틱이 이 배수(interval 기준)만큼 안 들어오면 "멈춘 것"으로 본다. 체크 시점이
# 다음 샘플링 직전일 수도 있어서 1배보다는 여유를 둔다.
STALE_MULTIPLIER = 3

# 시스템 시계가 약간 흔들리는(NTP 보정 등) 정도는 "미래 시각"으로 오판하지
# 않도록 두는 여유. 이걸 넘어서는 미래 시각은 시계가 실제로 뒤로 조정됐다고
# 보고 비정상으로 처리한다.
CLOCK_SKEW_TOLERANCE_SECONDS = 5.0


def _validate_expected_interval(expected_interval: float) -> None:
    """expected_interval이 유한한 양수인지 확인한다.

    argparse의 type=float만 쓰면 nan/inf/0/음수가 그대로 들어온다. nan이나
    +inf면 "elapsed > threshold" 비교가 항상 거짓이 되어 멈춘 recorder를
    계속 정상으로 오판하고, 0/음수면 반대로 정상인데도 멈춘 것으로
    오판한다. CLI(argparse)뿐 아니라 check()를 직접 호출하는 경우도 같은
    보장을 받도록 여기서 한 번 더 검증한다.
    """
    if not math.isfinite(expected_interval) or expected_interval <= 0:
        raise ValueError(f"expected_interval은 유한한 양수여야 합니다: {expected_interval}")


def _expected_interval_type(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}'는 숫자가 아닙니다.") from exc

    try:
        _validate_expected_interval(parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return parsed


def check(db_path: Path, expected_interval: float) -> tuple[bool, str]:
    """(건강한지, 사람이 읽을 메시지)를 반환한다."""
    _validate_expected_interval(expected_interval)

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
    except sqlite3.OperationalError:
        # recorder가 lock은 잡았지만 open_db()의 executescript()로 테이블을 만들기
        # 전인 아주 짧은 순간에 체크하면 "no such table: ticks"로 여기서 터진다.
        # 그냥 두면 check()가 (bool, str) 계약을 깨고 예외로 죽는다.
        return False, f"실행 중이지만 DB 스키마를 읽을 수 없습니다: {db_path}"
    finally:
        conn.close()

    if row is None:
        return False, "실행 중이지만 아직 기록된 틱이 없습니다."

    last_tick = datetime.fromisoformat(row[0])
    elapsed = (datetime.now(UTC) - last_tick).total_seconds()

    # elapsed가 음수면 마지막 틱이 "미래" 시각이라는 뜻이다. 틱을 기록한 뒤
    # 시스템 시계가 뒤로 조정되면 생길 수 있다 — 그 사이에 recorder가 멈춰도
    # 시계가 그 미래 시각을 따라잡을 때까지 계속 정상으로 보이게 된다.
    if elapsed < -CLOCK_SKEW_TOLERANCE_SECONDS:
        return False, (
            f"마지막 틱이 미래 시각입니다 ({-elapsed:.0f}초 앞선 {last_tick.isoformat()}) "
            "— 시스템 시계가 조정됐을 수 있습니다."
        )

    threshold = expected_interval * STALE_MULTIPLIER
    if elapsed > threshold:
        return False, (
            f"실행 중이지만 마지막 틱이 {elapsed:.0f}초 전입니다 "
            f"(기대 interval {expected_interval:.0f}초의 {STALE_MULTIPLIER}배인 "
            f"{threshold:.0f}초를 넘었습니다 — 멈춘 것으로 보입니다)."
        )

    return True, f"정상 — 마지막 틱 {elapsed:.0f}초 전 ({last_tick.isoformat()})."


def main() -> None:
    """CLI 인자를 파싱해서 check()를 실행하고, 결과를 메시지 + exit code로 돌려준다."""
    if sys.platform == "win32" and sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="recorder 헬스체크")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--expected-interval",
        type=_expected_interval_type,
        default=DEFAULT_INTERVAL_SECONDS,
        help="recorder를 실행할 때 준 --interval과 맞춰주세요.",
    )
    args = parser.parse_args()

    healthy, message = check(args.db_path, args.expected_interval)
    print(message)
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
