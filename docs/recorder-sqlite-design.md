# recorder → SQLite 저장 설계

`apps/recorder`가 매 interval마다 샘플링한 값을 SQLite에 어떻게 저장할지에 대한
설계 논의 기록. 결정한 내용과 왜 그렇게 결정했는지를 남겨둔다.

## 왜 SQLite인가 (DuckDB/MariaDB는 왜 아닌가)

- **MariaDB**: 서버 프로세스가 항상 떠 있어야 함. "로컬 우선 + 그냥 워커 실행"이라는
  이 프로젝트의 전제와 아키텍처적으로 안 맞아서 제외.
- **DuckDB**: 컬럼 스토리지 기반이라 "인덱스 없이 대량 스캔 + 복잡한 분석"에서
  강점이 나오는데, 이 앱의 집계는 결국 `GROUP BY process_name`류의 단순 합산이라
  인덱스 있는 SQLite와 비교해 실익이 없음. 나중에 복잡한 분석(다중 조인, 윈도우
  함수)이 실제로 필요해지면 그때 다시 검토.
- **SQLite**: 단일 파일, 서버 불필요, WAL 모드로 충분히 빠른 쓰기. 지금 요구사항에
  가장 적합. 나중에 멀티 디바이스 동기화가 필요해지면 SQLite 파일 포맷을 그대로
  쓰는 **libSQL(Turso)**로 이전하는 경로가 있음 — 지금 미리 도입하지는 않음.

## 암호화와 집계 가능성

암호화 방식에 따라 결과가 다르다:

- **파일 전체 암호화 (SQLCipher)**: DB를 열 때 키로 복호화해서 SQLite는 내부적으로
  평문 페이지를 다룸. **GROUP BY/집계가 평문 DB와 완전히 동일하게 동작**. 디스크에
  파일만 있고 앱이 꺼진 상태에서 노트북이 털리는 상황을 방어.
- **필드별 암호화** (예: `process_name` 컬럼 값 자체를 AES로): 같은 값도 암호화할
  때마다 다른 암호문이 나와서(안전하게 하려면 랜덤 IV 필요) `GROUP BY`가 깨짐 —
  전부 복호화해서 앱 코드에서 다시 묶어야 함. **이 프로젝트에서는 쓰지 않음.**

필요해지면 SQLCipher로 파일 전체 암호화를 적용한다. 지금은 보류 (필요할 때 추가).

## 저장 스키마

틱마다 세 가지를 기록해야 하는데 데이터 모양이 다르다 — foreground와 입력 활동은
틱당 1개, 윈도우 프로세스 목록은 틱당 0~N개. 이 모양을 그대로 테이블로 반영한다.

```sql
CREATE TABLE ticks (
    id INTEGER PRIMARY KEY,
    sampled_at TEXT NOT NULL,                -- ISO8601 UTC
    foreground_process TEXT,                  -- 못 가져왔으면 NULL
    seconds_since_last_input REAL NOT NULL    -- GetLastInputInfo 기반 idle 시간
);

CREATE TABLE tick_windowed_processes (
    tick_id INTEGER NOT NULL REFERENCES ticks(id) ON DELETE CASCADE,
    process_name TEXT NOT NULL,
    PRIMARY KEY (tick_id, process_name)
);

CREATE INDEX idx_ticks_sampled_at ON ticks(sampled_at);
CREATE INDEX idx_ticks_foreground_process ON ticks(foreground_process);
CREATE INDEX idx_tick_windowed_processes_name ON tick_windowed_processes(process_name);
```

`seconds_since_last_input`은 boolean("활동 있었음")이 아니라 연속값으로 저장한다.
"활동이 있었다고 볼 임계값"은 레코더가 아니라 **쿼리 시점**에 정한다
(`WHERE seconds_since_last_input < 5` 등) — 나중에 기준을 바꿔도 과거 데이터를
그대로 다시 해석할 수 있다.

쿼리 예시:

- FG였던 시간: `SELECT COUNT(*) FROM ticks WHERE foreground_process = 'Code.exe'`
- 떠 있었던(WIN) 시간: `SELECT COUNT(*) FROM tick_windowed_processes WHERE process_name = 'chrome.exe'`
- 진짜 몰입해서 쓴 시간 (FG + 입력 활동 동시):
  `SELECT COUNT(*) FROM ticks WHERE foreground_process = 'Code.exe' AND seconds_since_last_input < 5`

## 틱 처리 구조: 샘플링과 저장을 분리

"매 interval마다 함수를 호출해서 쏘는" 구조로 가면 테스트하기 쉬워지지만, 그
함수가 누적용 Counter나 DB 커넥션을 직접 건드리면 오히려 결합도가 올라간다.
해법은 **샘플링을 순수 함수로 만들고, 저장(side effect)을 분리**하는 것:

```python
def sample_tick() -> TickSample:
    """현재 시점의 상태를 읽어서 반환. DB/상태를 전혀 건드리지 않는 순수 함수."""
    return TickSample(
        sampled_at=...,
        foreground_process=get_foreground_process_name(),
        windowed_processes=get_windowed_process_names(),
        seconds_since_last_input=...,
    )
```

루프는 `sample_tick()`을 호출해서 받은 값을 `save_tick(conn, sample)`에 넘기기만
한다. `sample_tick()`은 아무 상태도 안 가지므로 단위 테스트에서 DB나 Counter를
목(mock)할 필요가 없고, `save_tick()`은 실제 SQLite(또는 테스트용 임시 DB)로
검증하면 된다. 이렇게 하면 결합도가 오히려 **낮아진다** — 지금처럼 while 루프
안에서 Counter를 직접 증가시키는 것보다 더 분리됨.

## 매 틱 SQLite 쓰기 vs 메모리 누적 — 오버헤드 비교

| | 틱당 오버헤드 | 크래시 시 손실 | 시간대별 타임라인 지원 |
|---|---|---|---|
| **메모리 누적** (현재 Counter 방식) | 매우 작음 (dict 증가, 수백 ns) | **프로세스 시작 이후 전체 데이터 손실** | 불가능 — 합계만 남고 "언제"가 사라짐 |
| **SQLite에 매 틱 INSERT** (raw 이벤트 로그, 위 스키마) | WAL 모드 + 틱당 트랜잭션 1개로 묶으면 보통 수 ms 이내. interval이 5~30초라 **무시 가능한 수준** | 마지막 커밋 이후의 현재 틱 1개만 손실 | 가능 — 원본 타임스탬프가 그대로 남음 |
| **SQLite 누적 테이블 UPDATE** (process별 총합만 유지) | INSERT보다 약간 비쌈(upsert) 수준이지만 여전히 무시 가능 | 마지막 커밋 이후 손실분만 | 불가능 — 합계만 남음 |

**결론**: interval이 5~30초 수준이면 매 틱 SQLite 쓰기의 오버헤드는 실질적으로
0에 가깝다. 반면 메모리 누적 방식은 크래시 시 전체 데이터를 잃고, README에 적힌
"시간대별 타임라인" 기능도 원본 타임스탬프가 있어야 가능하므로 애초에 합계만
남기는 방식으로는 구현할 수 없다. **매 틱을 SQLite에 raw row로 쓰는 방식**으로
간다 — 메모리 누적 레이어는 아예 없앤다.
