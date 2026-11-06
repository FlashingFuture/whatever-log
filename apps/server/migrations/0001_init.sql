-- 사용자와 로그인 토큰. `wrangler d1 migrations apply DB`가 순서대로 적용한다(docs/auth-design.md).

-- Google 계정 하나가 사용자 한 명이다. google_sub는 Google이 계정마다 주는 고유 값이라 이메일이 바뀌어도 같다.
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_sub TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 로그인할 때 발급한 토큰. 원문은 저장하지 않고 SHA-256 해시만 둔다(DB가 새도 토큰을 못 쓴다).
-- 사용자를 지우면 토큰도 같이 지워진다(계정 삭제).
CREATE TABLE tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX idx_tokens_user_id ON tokens(user_id);
