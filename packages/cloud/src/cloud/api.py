"""로그인한 사용자의 서버 API 클라이언트(목표·달성도). 서버 응답의 모양을 아는 곳은 이 파일뿐이다.

서버 쪽 규칙은 `docs/sync-design.md`의 "서버 API"와 `apps/server/src/sync/`가 원본이다. 이 클라이언트는 응답을
엄격하게 검사해(모양이 다르면 `ServerError`) 서버가 바뀌었는데 클라이언트가 조용히 틀린 값을 쓰는 일을 막는다.
토큰은 요청 헤더에만 쓰고 오류 메시지·로그에 담지 않는다.
"""

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from cloud.server_client import _USER_AGENT, Opener, open_without_redirects

_TIMEOUT_SECONDS = 15
_MAX_RESPONSE_BYTES = 256 * 1024


class ServerError(Exception):
    """서버가 요청을 받아들이지 않았거나 응답이 이상하다. status는 HTTP 상태(응답 자체가 이상하면 0)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        """상태 코드, 서버의 오류 코드, 사용자에게 보여 줄 수 있는 메시지를 담는다."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class NotAuthorized(ServerError):
    """토큰이 없거나 만료됐거나 폐기됐다(401). 다시 로그인해야 한다."""

    def __init__(self) -> None:
        """고정 메시지로 만든다."""
        super().__init__(401, "invalid_token", "로그인이 필요합니다. 다시 로그인해 주세요.")


class ServerUnreachable(Exception):
    """서버에 닿지 못했다(네트워크 끊김, 시간 초과). 다음 주기에 다시 시도하면 된다."""


@dataclass(frozen=True)
class RemoteGoal:
    """서버의 목표. 삭제된 목표(deleted)는 이름·목표 시간·요일 없이 id와 revision만 있다."""

    id: str
    deleted: bool
    revision: int
    updated_at: str
    name: str | None = None
    daily_target_minutes: int | None = None
    weekdays: frozenset[int] = frozenset()


class GoalConflict(ServerError):
    """목표를 보냈지만 서버가 받지 않았다(409). code는 conflict·goal_deleted·duplicate_name·too_many_goals이고,
    current는 서버에 있는 현재 값(없을 수 있다)이다."""

    def __init__(self, code: str, message: str, current: RemoteGoal | None) -> None:
        """서버가 준 오류 코드·메시지·현재 값을 담는다."""
        super().__init__(409, code, message)
        self.current = current


@dataclass(frozen=True)
class ProgressEntry:
    """한 기기의 (목표, 날짜) 달성 분과 그날의 목표 분."""

    goal_id: str
    day: str
    minutes: int
    target_minutes: int


@dataclass(frozen=True)
class ProgressResult:
    """달성도를 보낸 결과: 저장된 줄 수와, 서버에 없어 무시된(다른 기기에서 지운) 목표 id들."""

    accepted: int
    ignored_goal_ids: tuple[str, ...]


@dataclass(frozen=True)
class DayProgress:
    """서버가 합산한 (목표, 날짜)의 달성도."""

    goal_id: str
    day: str
    minutes: int
    target_minutes: int
    percent: int
    devices: int


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("정수가 아닙니다.")
    return value


def _parse_goal(item: Any) -> RemoteGoal:
    """서버의 목표 JSON을 RemoteGoal로. 모양이 다르면 ValueError/KeyError/TypeError."""
    if item["deleted"] is True:
        return RemoteGoal(id=str(item["id"]), deleted=True, revision=_int(item["revision"]), updated_at=str(item["updated_at"]))
    name = item["name"]
    weekdays = item["weekdays"]
    if not isinstance(name, str) or not isinstance(weekdays, list):
        raise ValueError("목표 모양이 다릅니다.")
    return RemoteGoal(
        id=str(item["id"]),
        deleted=False,
        revision=_int(item["revision"]),
        updated_at=str(item["updated_at"]),
        name=name,
        daily_target_minutes=_int(item["daily_target_minutes"]),
        weekdays=frozenset(_int(day) for day in weekdays),
    )


class ServerApi:
    """Bearer 토큰으로 서버의 목표·달성도 API를 부른다. opener는 테스트용이다."""

    def __init__(self, server_url: str, token: str, *, opener: Opener = open_without_redirects) -> None:
        """서버 주소와 로그인 토큰을 받는다."""
        self._base = server_url
        self._token = token
        self._opener = opener

    def _call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        """요청을 보내고 (상태, JSON 본문 또는 None)을 돌려준다. 2xx가 아니면 ServerError 계열을 올린다."""
        headers = {"Authorization": f"Bearer {self._token}", "User-Agent": _USER_AGENT, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self._base}{path}", data=data, headers=headers, method=method)
        try:
            with self._opener(request, timeout=_TIMEOUT_SECONDS) as response:
                raw = response.read(_MAX_RESPONSE_BYTES)
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            raise self._to_error(error) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise ServerUnreachable from None
        except ValueError:
            raise ServerError(0, "bad_response", "서버 응답을 이해하지 못했습니다.") from None

    @staticmethod
    def _to_error(error: urllib.error.HTTPError) -> ServerError:
        """HTTP 오류 응답을 ServerError(또는 NotAuthorized·GoalConflict)로 바꾼다."""
        try:
            payload = json.loads(error.read(_MAX_RESPONSE_BYTES))
        except (OSError, http.client.HTTPException, ValueError):
            payload = None
        if error.code == 401:
            return NotAuthorized()
        if 300 <= error.code < 400:
            return ServerError(error.code, "redirect", "서버가 다른 주소로 보내려 해서 요청하지 않았습니다.")
        info = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = info.get("code") if isinstance(info.get("code"), str) else "error"
        message = info.get("message") if isinstance(info.get("message"), str) else f"서버가 요청을 거부했습니다({error.code})."
        if error.code == 409:
            current = None
            if isinstance(payload, dict) and isinstance(payload.get("current"), dict):
                try:
                    current = _parse_goal(payload["current"])
                except (KeyError, ValueError, TypeError):
                    current = None
            return GoalConflict(code, message, current)
        return ServerError(error.code, code, message)

    def list_goals(self) -> list[RemoteGoal]:
        """내 목표 전부(삭제 표시 포함)."""
        _, payload = self._call("GET", "/goals")
        try:
            return [_parse_goal(item) for item in payload["goals"]]
        except (KeyError, ValueError, TypeError):
            raise ServerError(0, "bad_response", "서버 응답을 이해하지 못했습니다.") from None

    def put_goal(
        self,
        goal_id: str,
        *,
        name: str,
        daily_target_minutes: int,
        weekdays: Collection[int],
        base_revision: int,
    ) -> RemoteGoal:
        """목표를 만들거나(base_revision 0) 고친다. 서버가 받지 않으면 GoalConflict(409) 등을 올린다."""
        _, payload = self._call(
            "PUT",
            f"/goals/{goal_id}",
            {
                "name": name,
                "daily_target_minutes": daily_target_minutes,
                "weekdays": sorted(weekdays),
                "base_revision": base_revision,
            },
        )
        try:
            return _parse_goal(payload)
        except (KeyError, ValueError, TypeError):
            raise ServerError(0, "bad_response", "서버 응답을 이해하지 못했습니다.") from None

    def delete_goal(self, goal_id: str) -> bool:
        """목표를 삭제한다. 서버에 없는 목표(404)면 False(이미 없으니 목적은 이뤄졌다)."""
        try:
            self._call("DELETE", f"/goals/{goal_id}")
        except ServerError as error:
            if error.status == 404:
                return False
            raise
        return True

    def put_progress(self, device_id: str, entries: Sequence[ProgressEntry]) -> ProgressResult:
        """이 기기의 (목표, 날짜) 달성 줄을 덮어쓴다(서버는 한 번에 50줄까지 받는다)."""
        _, payload = self._call(
            "PUT",
            "/progress",
            {
                "device_id": device_id,
                "entries": [
                    {"goal_id": e.goal_id, "day": e.day, "minutes": e.minutes, "target_minutes": e.target_minutes}
                    for e in entries
                ],
            },
        )
        try:
            ignored = payload["ignored_goal_ids"]
            if not isinstance(ignored, list):
                raise ValueError
            return ProgressResult(accepted=_int(payload["accepted"]), ignored_goal_ids=tuple(str(item) for item in ignored))
        except (KeyError, ValueError, TypeError):
            raise ServerError(0, "bad_response", "서버 응답을 이해하지 못했습니다.") from None

    def get_progress(self, start: str, end: str) -> list[DayProgress]:
        """[start, end] 날짜(YYYY-MM-DD) 구간의 합산 달성도."""
        _, payload = self._call("GET", "/progress?" + urlencode({"from": start, "to": end}))
        try:
            return [
                DayProgress(
                    goal_id=str(item["goal_id"]),
                    day=str(item["day"]),
                    minutes=_int(item["minutes"]),
                    target_minutes=_int(item["target_minutes"]),
                    percent=_int(item["percent"]),
                    devices=_int(item["devices"]),
                )
                for item in payload["days"]
            ]
        except (KeyError, ValueError, TypeError):
            raise ServerError(0, "bad_response", "서버 응답을 이해하지 못했습니다.") from None


#: 서버 API 클라이언트를 만드는 함수(서버 주소, 토큰) — 호출부가 테스트에서 가짜로 바꿀 수 있다.
ApiFactory = Callable[[str, str], ServerApi]
