-- 목표 기간(docs/goal-management.md "C. 기간의 서버 동기화"). 둘 다 비어 있으면 기간 없음(무기한, 기존 목표 전부).
-- 날짜는 사용자의 로컬 날짜(YYYY-MM-DD, 양끝 포함)다 — 서버는 시간대를 모른다. 둘이 함께 있어야 하고 시작 ≤ 종료라는 규칙은
-- API(goalInput.ts)가 확인한다(ADD COLUMN의 CHECK는 그 칸만 볼 수 있다). 여기서는 모양만 막는다.
ALTER TABLE goals ADD COLUMN start_date TEXT
    CHECK (start_date IS NULL OR start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]');
ALTER TABLE goals ADD COLUMN end_date TEXT
    CHECK (end_date IS NULL OR end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]');
