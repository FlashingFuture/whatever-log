-- 메일 발송 기록(docs/mail-design.md). 하루 발송량을 세서 한도(사용자별·서버 전체)를 넘기 전에 멈추는 데 쓴다. 본문·제목·주소는 담지 않는다.
-- 사용자를 지우면 같이 지워진다(계정 삭제).
CREATE TABLE mail_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- test: 사용자가 요청한 시험 메일 / report: 보고서 메일(예정)
    kind TEXT NOT NULL CHECK (kind IN ('test', 'report')),
    -- 발송한 날(UTC, YYYY-MM-DD). 일일 한도를 이 날짜로 센다.
    sent_on TEXT NOT NULL,
    -- 한도 확인과 자리 잡기를 한 문장으로 하려고 먼저 넣는 행의 고유 값. 발송에 실패하면 이 값으로 행을 지운다.
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    -- 서비스가 돌려준 접수 번호(발송에 성공한 뒤 채운다).
    provider_id TEXT
);

CREATE INDEX idx_mail_sends_day ON mail_sends(sent_on, user_id, kind);
