"""목표 저장·검증에서 나는 오류. 호출부(hub 등)가 API 오류 응답으로 바꿔 쓰기 좋게 구조를 갖는다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldError:
    """입력 한 칸의 오류. code는 기계가 보는 값(화면이 칸 옆에 표시할 때 구분), message는 사용자에게 보일 설명."""

    field: str
    code: str
    message: str


class GoalValidationError(ValueError):
    """입력이 규칙에 맞지 않는다. 고칠 수 있게 모든 칸의 오류를 한꺼번에 담는다(첫 오류만 알리지 않는다)."""

    def __init__(self, errors: list[FieldError]) -> None:
        """칸별 오류 목록을 담고, 예외 메시지는 그 요약으로 만든다."""
        self.errors = tuple(errors)
        super().__init__("; ".join(f"{error.field}: {error.message}" for error in self.errors))


class GoalNotFoundError(LookupError):
    """그 id의 목표가 없다."""


class SchemaVersionError(RuntimeError):
    """goals.db가 이 코드보다 새 버전으로 만들어졌다 — 옛 코드가 새 스키마를 잘못 다루지 않게 연결을 거부한다."""


class StaleSyncError(RuntimeError):
    """동기화가 시작된 뒤에 계정 정리(`reset_sync`)가 일어났다 — 이전 계정의 주기가 낡은 결과를 저장하지 못하게 거절한다.

    에이전트는 이것을 받으면 이번 주기를 버리고 다음 주기에 새 세대로 다시 시작한다.
    """
