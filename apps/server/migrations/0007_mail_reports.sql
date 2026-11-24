-- 보고서 발송 기록(docs/mail-design.md "보고서 발송 (E)"). (구독, 구간)마다 한 줄 — 같은 구간을 두 번 보내지 않는 보장이다.
-- Cron이 겹쳐 돌아도 먼저 자리를 잡은(INSERT) 쪽만 보낸다. 주소·제목·본문은 담지 않는다.
CREATE TABLE mail_reports (
    subscription_id TEXT NOT NULL REFERENCES mail_subscriptions(id) ON DELETE CASCADE,
    -- 보낼 날(구독의 시간대 기준 YYYY-MM-DD). 이 날짜가 다루는 구간은 주기로 정해진다(전날·지난주·지난달).
    period_key TEXT NOT NULL CHECK (period_key GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    -- sending: 보내는 중(자리를 잡았다) / sent: 보냈다 / failed: 서비스가 거절했다(이 구간은 다시 보내지 않는다)
    -- unknown: 요청은 했지만 접수됐는지 모른다 — 멱등 키가 살아 있는 동안(첫 시도부터 23시간)만 같은 키로 다시 보내고, 그 뒤로는 다시 보내지 않는다
    status TEXT NOT NULL CHECK (status IN ('sending', 'sent', 'failed', 'unknown')),
    provider_id TEXT,
    -- 처음 자리를 잡은 시각(= 첫 발송 시도). 다시 잡아도 바꾸지 않는다 — 멱등 키의 유효 기간을 이 시각부터 센다.
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (subscription_id, period_key)
);
