"""foreground 프로세스와, 창이 있는 전체 프로세스(foreground 포함)를
각각 독립적으로 샘플링해서 카운트를 쌓는 워커.

사용법: python -m recorder --interval 5
"""

import argparse
import sys
import time
from collections import Counter

from recorder.window_snapshot import (
    get_foreground_process_name,
    get_windowed_process_names,
)

DEFAULT_INTERVAL_SECONDS = 15.0

# Python 3.14는 아직 Windows에서 UTF-8을 기본으로 쓰지 않는다(3.15부터 기본값).
# 터미널 코드페이지에 따라 한글이 깨지는 걸 막기 위해 명시적으로 맞춘다.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def _print_tick(tag: str, name: str, counts: Counter[str]) -> None:
    print(f"[{tag}][{name}] {counts[name]}회  (전체: {dict(counts)})")


def run(interval: float) -> None:
    foreground_counts: Counter[str] = Counter()
    window_counts: Counter[str] = Counter()
    print(
        f"{interval}초 간격으로 foreground / 전체 윈도우 프로세스를 "
        "독립적으로 기록합니다. (Ctrl+C로 종료)"
    )

    try:
        while True:
            foreground = get_foreground_process_name()
            if foreground is not None:
                foreground_counts[foreground] += 1
                _print_tick("FG", foreground, foreground_counts)

            for name in get_windowed_process_names():
                window_counts[name] += 1
                _print_tick("WIN", name, window_counts)

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n종료합니다. 최종 집계:")
        print("  [foreground]")
        for name, count in foreground_counts.most_common():
            print(f"    {name}: {count}")
        print("  [windowed (foreground 포함)]")
        for name, count in window_counts.most_common():
            print(f"    {name}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="foreground / 전체 윈도우 프로세스 기록 워커")
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
