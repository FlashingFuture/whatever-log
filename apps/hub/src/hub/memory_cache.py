"""이미지(PNG 바이트)를 메모리에 잠시 들고 있는 캐시 — 프로세스 아이콘과 사이트 아이콘이 같이 쓴다.

캐시가 같아야 하는 규칙을 한곳에 둔다:

- 크기 제한(LRU): 가장 오래 안 쓴 것부터 밀어낸다.
- 만료(선택): ttl_seconds를 주면 그 시간이 지난 항목은 없는 것으로 본다. 원본이 바뀌어도 키가
  그대로인 경우(사이트 아이콘은 도메인이 키라 브라우저가 아이콘을 바꾸거나 기록을 지워도 키가
  같다)에 필요하다. 키가 내용을 담고 있으면(프로세스 아이콘: 경로+수정시각+크기) 줄 필요가 없다.
- 없음 기억: 찾지 못한 키를 잠시 "없음"으로 기억해서, 같은 요청마다 비싼 조회(Win32 호출,
  브라우저 파일 복사)를 되풀이하지 않는다. 잠깐의 실패가 영원히 남지 않게 유한하다.
- 키별 잠금: 같은 키를 여러 요청이 동시에 달라고 해도 조회는 한 번만 하도록, 호출부가 잠금을
  잡은 뒤 캐시를 다시 확인한다(차트가 이미지를 한꺼번에 요청하므로 흔한 상황이다).
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

DEFAULT_MAX_ENTRIES = 256
# 아이콘이 없다고 판단한 결과를 기억하는 시간.
DEFAULT_MISSING_TTL_SECONDS = 300.0


class ImageMemoryCache:
    """키 → 이미지 바이트. 위 모듈 설명의 LRU·만료·없음 기억·키별 잠금을 맡는다. 스레드 안전하다."""

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float | None = None,
        missing_ttl_seconds: float = DEFAULT_MISSING_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._missing_ttl_seconds = missing_ttl_seconds
        self._clock = clock
        # 키 -> (이미지, 만료 시각 또는 None)
        self._entries: OrderedDict[str, tuple[bytes, float | None]] = OrderedDict()
        self._missing_until: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: str) -> bytes | None:
        """들고 있는 이미지. 없거나 만료됐으면 None(만료된 항목은 지운다)."""
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                return None
            image, expires_at = entry
            if expires_at is not None and self._clock() >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return image

    def put(self, key: str, image: bytes) -> None:
        """이미지를 넣는다. 있던 "없음" 기억은 지우고, 크기 제한을 넘으면 오래된 것을 밀어낸다."""
        with self._guard:
            expires_at = None if self._ttl_seconds is None else self._clock() + self._ttl_seconds
            self._entries[key] = (image, expires_at)
            self._entries.move_to_end(key)
            self._missing_until.pop(key, None)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def is_missing(self, key: str) -> bool:
        """최근에 찾아봤지만 없었던 키인지(기억이 만료됐으면 False)."""
        with self._guard:
            until = self._missing_until.get(key)
            if until is None:
                return False
            if self._clock() >= until:
                del self._missing_until[key]
                return False
            return True

    def mark_missing(self, key: str) -> None:
        """찾아봤지만 없었다고 잠시 기억한다."""
        with self._guard:
            self._missing_until[key] = self._clock() + self._missing_ttl_seconds

    def lock_for(self, key: str) -> threading.Lock:
        """이 키의 조회를 직렬화하는 잠금. 잡은 뒤에 get/is_missing을 다시 확인한다."""
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())
