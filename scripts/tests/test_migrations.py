"""서버 마이그레이션은 추가만 한다(docs/deploy.md 규칙 1) — 새 마이그레이션에 칸·테이블을 지우거나 이름을 바꾸는 문장이 없는지 본다.

마이그레이션은 새 Worker보다 먼저 적용되고 되돌리지 않으므로, 이전 Worker가 새 DB에서 돌아야 한다. 정말 필요하면(두 번에 나눈 정리의 두 번째 등)
아래 허용 목록에 파일 이름과 이유를 올린다.
"""

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "apps" / "server" / "migrations"

# 이 규칙 전에 있던 파일, 또는 이유가 있어 허용한 파일 → 이유
ALLOWED = {
    "0004_mail_sends_by_account_hash.sql": "운영에 적용된 적 없는 0003의 시험 발송 기록 테이블을 바꿨다(규칙 전, docs/mail-design.md)",
    "0006_mail_subscriptions.sql": "mail_sends.kind의 CHECK에 welcome을 더하려고 같은 칸의 새 테이블로 옮겼다(칸·의미는 그대로라 이전 Worker도 돈다)",
}

_DESTRUCTIVE = re.compile(r"\b(DROP\s+(TABLE|COLUMN|INDEX|VIEW|TRIGGER)|RENAME\s+(TO|COLUMN))\b", re.IGNORECASE)


def _statements(sql: str) -> str:
    """주석(`-- …`, `/* … */`)을 뺀 SQL."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def test_migrations_only_add() -> None:
    found = {
        path.name: match.group(0)
        for path in sorted(MIGRATIONS.glob("*.sql"))
        if path.name not in ALLOWED and (match := _DESTRUCTIVE.search(_statements(path.read_text(encoding="utf-8"))))
    }
    assert found == {}, f"추가만 하는 마이그레이션 규칙(docs/deploy.md)에 어긋납니다: {found}"


def test_the_check_catches_destructive_statements_but_not_comments() -> None:
    assert _DESTRUCTIVE.search(_statements("ALTER TABLE goals DROP COLUMN name;"))
    assert _DESTRUCTIVE.search(_statements("alter table goals rename to old_goals;"))
    assert _DESTRUCTIVE.search(_statements("DROP INDEX idx_x;"))
    assert not _DESTRUCTIVE.search(_statements("-- DROP TABLE는 쓰지 않는다\nALTER TABLE goals ADD COLUMN x TEXT;"))
    assert not _DESTRUCTIVE.search(_statements("/* RENAME TO 금지 */ CREATE TABLE t (id INTEGER);"))


def test_allowed_files_still_exist() -> None:
    """허용 목록이 사라진 파일을 붙들고 있지 않게(이름을 잘못 적으면 그 파일이 검사에서 빠진다)."""
    assert all((MIGRATIONS / name).is_file() for name in ALLOWED)
