-- 보고서 메일 구독(docs/mail-design.md "구독", docs/goal-management.md "D"). 발송(Cron)과 보고서 본문은 E에서 붙는다.

-- 사용자의 요금제. 지금은 free뿐이다 — 매일 구독자 상한 같은 게이트를 요금제에 묶어 둘 자리다(결제는 범위 밖).
ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free'));

-- 구독: **사용자당 하나**(user_id UNIQUE). 개인당 한 목표에만 보낸다는 규칙의 진실은 이 제약이다 — 확인 후 저장은 동시 요청에 뚫리므로
-- 저장은 INSERT … ON CONFLICT(user_id)로 한다. id는 무작위 UUID로, 메일의 멱등 키와 수신 거부 링크(서명)에 쓴다.
CREATE TABLE mail_subscriptions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    -- daily: 매일(전날 하루) / weekly: 매주(지난 월~일) / monthly: 매월(지난달)
    frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
    -- 매주일 때만: 보낼 요일(월=0 … 일=6, 목표의 요일과 같은 번호)
    weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
    -- 매월일 때만: 보낼 날(1~28 — 29~31일이 없는 달이 있다)
    day_of_month INTEGER CHECK (day_of_month BETWEEN 1 AND 28),
    -- 보낼 시각(사용자의 시간대, HH:MM)
    send_time TEXT NOT NULL CHECK (send_time GLOB '[0-2][0-9]:[0-5][0-9]' AND send_time <= '23:59'),
    -- 사용자의 시간대(IANA, 예: Asia/Seoul). 구간("전날", "지난주")과 보낼 시각을 이 시간대로 계산한다.
    timezone TEXT NOT NULL CHECK (length(timezone) BETWEEN 1 AND 64),
    -- active: 발송 중 / paused: 사용자가 끔 / ended: 자동으로 끝남(ended_reason)
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'ended')),
    ended_reason TEXT CHECK (ended_reason IN ('goal_deleted', 'goal_ended', 'unsubscribed', 'suppressed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((frequency = 'weekly') = (weekday IS NOT NULL)),
    CHECK ((frequency = 'monthly') = (day_of_month IS NOT NULL)),
    CHECK ((status = 'ended') = (ended_reason IS NOT NULL)),
    FOREIGN KEY (user_id, goal_id) REFERENCES goals(user_id, id) ON DELETE CASCADE
);

-- 발송(E)이 "지금 보낼 구독"과 "매일 구독자 수"를 고를 때 쓴다.
CREATE INDEX idx_mail_subscriptions_status ON mail_subscriptions(status, frequency);

-- 첫 신청 확인 메일을 보낸 사용자. **계정과 무관한 키**(sha256("mail:" + google_sub), mail_sends와 같은 값)로 영구히 남긴다 — 신청·해지·계정 삭제를
-- 되풀이해 확인 메일을 다시 받거나(메일 폭탄) 한도를 쓰지 못하게. 해시와 시각뿐이다.
CREATE TABLE mail_welcomes (
    user_key TEXT PRIMARY KEY CHECK (length(user_key) = 64),
    welcomed_at TEXT NOT NULL
);

-- 보내지 않을 주소: 반송(영구)·스팸 신고가 온 주소. 주소 원문이 아니라 sha256("address:" + 소문자 주소)만 둔다 — 계정을 지웠다 다시 만들어도
-- 같은 주소면 다시 보내지 않는다(새 도메인의 평판을 지킨다).
CREATE TABLE mail_suppressions (
    address_hash TEXT PRIMARY KEY CHECK (length(address_hash) = 64),
    reason TEXT NOT NULL CHECK (reason IN ('bounced', 'complained')),
    created_at TEXT NOT NULL
);

-- 발송 기록에 확인 메일(welcome)을 더한다. CHECK는 고칠 수 없어 같은 칸의 새 테이블로 옮긴다(칸·의미는 그대로라 이전 Worker도 그대로 돈다).
CREATE TABLE mail_sends_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_key TEXT NOT NULL CHECK (length(user_key) = 64),
    -- test: 시험 메일 / report: 보고서 메일(E) / welcome: 첫 신청 확인 메일
    kind TEXT NOT NULL CHECK (kind IN ('test', 'report', 'welcome')),
    sent_on TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    provider_id TEXT
);
INSERT INTO mail_sends_new (id, user_key, kind, sent_on, token, created_at, provider_id)
    SELECT id, user_key, kind, sent_on, token, created_at, provider_id FROM mail_sends;
DROP INDEX IF EXISTS idx_mail_sends_day;
DROP TABLE mail_sends;
ALTER TABLE mail_sends_new RENAME TO mail_sends;
CREATE INDEX idx_mail_sends_day ON mail_sends(sent_on, user_key, kind);
