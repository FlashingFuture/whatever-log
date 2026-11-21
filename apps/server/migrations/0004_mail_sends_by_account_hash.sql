-- 발송 기록을 계정 행과 분리한다(코드 리뷰 반영, docs/mail-design.md).
--
-- 0003은 mail_sends가 users를 참조하고 계정을 지우면 함께 지워졌다. 그러면 "시험 메일 발송 → 계정 삭제 → 재로그인"을 반복해 하루 한도를 넘길 수 있다
-- (삭제로 발송 횟수가 사라지고, 재로그인은 새 users 행을 만들어 사용자별 횟수도 0부터 다시 센다). 그래서 사용자를 **계정과 무관한 키**로 가리킨다:
-- Google 계정의 고유 값(sub)의 SHA-256. 같은 Google 계정은 삭제·재로그인 뒤에도 같은 키라 한도가 이어진다. 이메일·sub 원문은 담지 않는다.
-- 외래 키도 없다(계정 삭제가 이 기록을 지우지 않는다). 쌓이지 않게 오래된 행은 발송할 때 지운다(testMail.ts의 RETENTION_DAYS).
--
-- 0003은 운영에 적용된 적이 없고 시험 발송 기록뿐이라 옮기지 않고 버린다.
DROP INDEX IF EXISTS idx_mail_sends_day;
DROP TABLE IF EXISTS mail_sends;

CREATE TABLE mail_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- sha256("mail:" + google_sub)의 16진 문자열(64자). 계정(users.id)이 아니라 Google 계정을 가리킨다.
    user_key TEXT NOT NULL CHECK (length(user_key) = 64),
    -- test: 사용자가 요청한 시험 메일 / report: 보고서 메일(예정)
    kind TEXT NOT NULL CHECK (kind IN ('test', 'report')),
    -- 발송한 날(UTC, YYYY-MM-DD). 일일 한도를 이 날짜로 센다.
    sent_on TEXT NOT NULL,
    -- 한도 확인과 자리 잡기를 한 문장으로 하려고 먼저 넣는 행의 고유 값.
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    -- 서비스가 돌려준 접수 번호(발송에 성공한 뒤 채운다).
    provider_id TEXT
);

CREATE INDEX idx_mail_sends_day ON mail_sends(sent_on, user_key, kind);
