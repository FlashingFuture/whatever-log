-- 목표와 기기별 달성도(docs/sync-design.md). 목표와 프로세스·사이트의 연결은 서버에 두지 않는다.

-- 사용자 한 명의 목표. id는 클라이언트가 만든 UUID라 다른 사용자와 겹칠 수 있어 (user_id, id)가 키다.
-- 삭제하면 행을 지우지 않고 deleted_at을 채우고 이름을 비운다(다른 기기가 삭제를 알 수 있게 30일 둔다).
CREATE TABLE goals (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    daily_target_minutes INTEGER NOT NULL CHECK (daily_target_minutes BETWEEN 1 AND 1440),
    -- 월=bit0 … 일=bit6
    weekdays INTEGER NOT NULL CHECK (weekdays BETWEEN 0 AND 127),
    -- 수정할 때마다 1씩 올린다. 두 기기가 동시에 고치면 늦은 쪽이 409를 받는다.
    revision INTEGER NOT NULL CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT,
    PRIMARY KEY (user_id, id)
);

-- 살아 있는 목표끼리는 이름이 겹치지 않는다(대소문자·유니코드 표현 차이는 name_key로 같게 본다).
CREATE UNIQUE INDEX idx_goals_live_name ON goals(user_id, name_key) WHERE deleted_at IS NULL;

-- (목표, 기기, 날짜)마다 한 줄. 각 기기는 자기 줄만 써서 기기끼리 충돌하지 않는다. 합산은 읽을 때 한다.
-- target_minutes는 그날 그 기기가 적용한 목표량이다(목표를 나중에 바꿔도 지난 날 달성률이 바뀌지 않게).
CREATE TABLE progress (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    goal_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    day TEXT NOT NULL,
    minutes INTEGER NOT NULL CHECK (minutes BETWEEN 0 AND 1440),
    target_minutes INTEGER NOT NULL CHECK (target_minutes BETWEEN 1 AND 1440),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, goal_id, device_id, day),
    FOREIGN KEY (user_id, goal_id) REFERENCES goals(user_id, id) ON DELETE CASCADE
);

CREATE INDEX idx_progress_user_day ON progress(user_id, day);
CREATE INDEX idx_progress_user_device ON progress(user_id, device_id);
