"""활성 프로세스를 주기적으로 샘플링해서 카운트를 쌓는 워커.

사용법: python -m recorder --interval 5
"""

import argparse
import sys
import time
from collections import Counter

from recorder.active_window import get_active_process_name

DEFAULT_INTERVAL_SECONDS = 15.0

# Python 3.14는 아직 Windows에서 UTF-8을 기본으로 쓰지 않는다(3.15부터 기본값).
# 터미널 코드페이지에 따라 한글이 깨지는 걸 막기 위해 명시적으로 맞춘다.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def run(interval: float) -> None:
    counts: Counter[str] = Counter()
    print(f"{interval}초 간격으로 활성 프로세스를 기록합니다. (Ctrl+C로 종료)")

    try:
        while True:
            name = get_active_process_name()
            if name is not None:
                counts[name] += 1
                print(f"[{name}] {counts[name]}회  (전체: {dict(counts)})")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n종료합니다. 최종 집계:")
        for name, count in counts.most_common():
            print(f"  {name}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="활성 프로세스 기록 워커")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"샘플링 간격(초), 기본 {DEFAULT_INTERVAL_SECONDS}초",
    )
    args = parser.parse_args()
    run(args.interval)


if __name__ == "__main__":
    main()
