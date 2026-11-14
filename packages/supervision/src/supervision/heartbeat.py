"""멈춤(hang) 감지를 위한 박동(heartbeat): 자식 프로세스는 "살아서 일하고 있다"는 신호만 내고, 판단과 조치는 supervisor가 한다.

supervisor는 원래 프로세스가 **끝났을 때**만 반응한다. 프로세스가 떠 있지만 아무 일도 못 하는 상태(잠금 대기, 외부 호출이 안 끝남 등)는 알 수 없다.
이 모듈이 그 빈틈을 메운다 — 책임은 이렇게 나뉜다:

- **자식(에이전트)**: 한 주기가 끝날 때마다 `beat()`를 부른다. 그게 전부다. 어디에 적는지도, 얼마나 기다려 주는지도 모른다.
- **supervisor**: `Heartbeat`(박동 파일과 허용 시간)를 받아 `HeartbeatWatch`로 지켜본다. 허용 시간 넘게 박동이 없으면 자식을 종료해 크래시처럼 다시 띄운다.
  에이전트마다 다른 것은 **주기뿐**이라 허용 시간만 `Heartbeat`로 받는다 — 감시·종료·재시작·포기 규칙은 supervisor 한 곳에 있다.
- **`status` 같은 보는 쪽**: `age_seconds()`로 마지막 박동이 얼마나 오래됐는지만 읽는다.

박동은 파일의 수정 시각이다. supervisor는 그 시각의 **값**이 바뀌는지를 자기 시계로 관찰한다(파일 시각과 시계를 비교하지 않는다) — 그래서 시계가 조정돼도
영향이 없다. 파일 경로는 환경 변수(`WHATEVER_LOG_HEARTBEAT_FILE`)로 자식에게 전해지고, 환경 변수가 없으면(supervisor 없이 직접 실행) `beat()`는 아무것도 하지 않는다.
"""

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: supervisor가 자식에게 박동 파일 경로를 알려 주는 환경 변수.
ENV_VAR = "WHATEVER_LOG_HEARTBEAT_FILE"

#: 감시 루프가 이만큼 넘게 멈췄다 돌아왔다면 PC가 절전에 들어갔다 깨어난 것으로 본다. 그 동안은 자식도 못 돌았으니 박동이 없었던 것을 탓하지 않고
#: 허용 시간을 처음부터 다시 센다(안 그러면 절전에서 깨어난 직후 멀쩡한 자식을 죽인다).
SUSPEND_GAP_SECONDS = 10.0


@dataclass(frozen=True)
class Heartbeat:
    """supervisor에게 넘기는 감시 설정.

    path는 박동 파일. startup_grace_seconds는 시작한 뒤 **첫 박동**까지 기다려 주는 시간(모듈을 불러오고 DB를 여는 동안), stale_after_seconds는 첫 박동 뒤에
    박동이 이만큼 끊기면 멈춘 것으로 보는 시간이다. 에이전트의 주기보다 충분히 커야 한다(주기의 몇 배).
    """

    path: Path
    stale_after_seconds: float
    startup_grace_seconds: float

    def __post_init__(self) -> None:
        """허용 시간이 유한한 양수인지 확인한다 — nan·inf·0·음수면 멈춘 프로세스를 영원히 정상으로 보거나 정상인데도 죽인다."""
        for name in ("stale_after_seconds", "startup_grace_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name}은 유한한 양수여야 합니다: {value}")


def beat() -> None:
    """"살아서 일하고 있다"는 신호를 낸다. supervisor가 정해 준 박동 파일의 수정 시각을 지금으로 바꾼다(없으면 만든다).

    supervisor 없이 실행됐거나(환경 변수 없음) 파일을 쓸 수 없어도 예외를 내지 않는다 — 박동은 부가 기능이라 이것 때문에 에이전트가 죽으면 안 된다.
    쓰지 못하면 supervisor는 박동이 끊긴 것으로 보고 자식을 다시 띄우는데, 쓸 수 없는 이유가 계속되면 크래시 루프 규칙이 결국 포기한다.
    """
    path = os.environ.get(ENV_VAR)
    if not path:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    except OSError:
        pass


def age_seconds(path: Path, *, now: Callable[[], float] = time.time) -> float | None:
    """마지막 박동이 몇 초 전인지(`status`가 보여 주는 값). 박동 파일이 없거나 읽을 수 없으면 None.

    파일 시각과 지금 시계를 비교하므로 절전에서 막 깨어난 직후에는 실제보다 크게 나올 수 있다(보여 주는 용도일 뿐 감시에는 쓰지 않는다).
    """
    try:
        modified = path.stat().st_mtime
    except OSError:
        return None
    return max(0.0, now() - modified)


def _modified_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


class HeartbeatWatch:
    """자식 하나(한 번의 실행)의 박동을 지켜보는 순수한 상태 기계. 시계와 파일 읽기를 주입할 수 있어 프로세스 없이 시험한다."""

    def __init__(
        self,
        heartbeat: Heartbeat,
        *,
        started_at: float,
        read_modified: Callable[[Path], int | None] = _modified_ns,
    ) -> None:
        """감시를 시작한다. 이전 실행이 남긴 박동 파일은 지운다(지우지 못해도, 지금 값을 기준으로 삼아 "바뀌었는가"만 본다)."""
        self._heartbeat = heartbeat
        self._read = read_modified
        try:
            heartbeat.path.unlink(missing_ok=True)
        except OSError:
            pass
        self._last_modified = read_modified(heartbeat.path)
        self._last_beat_at = started_at
        self._previous_check_at = started_at
        self._beaten = False

    def is_hung(self, now: float) -> bool:
        """지금(감시자의 단조 시계) 자식이 멈춘 것으로 봐야 하는가. 감시 루프가 돌 때마다 부른다."""
        if now - self._previous_check_at > SUSPEND_GAP_SECONDS:
            self._last_beat_at = now  # 감시자 자신이 멈췄다 돌아왔다(절전 등) — 허용 시간을 다시 센다
        self._previous_check_at = now
        modified = self._read(self._heartbeat.path)
        if modified is not None and modified != self._last_modified:
            self._last_modified = modified
            self._last_beat_at = now
            self._beaten = True
        limit = self._heartbeat.stale_after_seconds if self._beaten else self._heartbeat.startup_grace_seconds
        return now - self._last_beat_at > limit

    @property
    def silent_seconds_limit(self) -> float:
        """지금 단계(첫 박동 전/후)에서 허용하는 침묵 시간. 로그에 적는 값이다."""
        return self._heartbeat.stale_after_seconds if self._beaten else self._heartbeat.startup_grace_seconds
