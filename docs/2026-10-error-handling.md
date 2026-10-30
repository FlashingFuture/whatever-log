# 에러 처리 현황과 공통화 후보

whatever.log는 Python(recorder, hub, desktop)과 TypeScript(apps/ui)로 나뉘어 있고,
대부분 콘솔 없이(`pythonw.exe`, pywebview 창) 돌아간다. 그래서 에러 처리의 공통
원칙은 하나다: **원인이 어딘가에는 남아야 하고, 사용자가 아무것도 못 보는 상태로
조용히 죽으면 안 된다.** 이 문서는 지금 코드가 그걸 어떻게 하고 있는지 정리하고,
나중에 공통 모듈로 빼거나 언어별로 규칙을 맞출 때 기준이 되도록 후보를 적어둔다.

## 1. 환경 제약 (왜 이렇게 처리하는지)

- `pythonw.exe`로 띄우면 `sys.stdout`/`sys.stderr`가 `None`이다. `print`나
  traceback 출력이 어디에도 안 남는다 → **파일 로그가 유일한 기록**이다.
- 백그라운드 프로세스는 supervisor가 재시작한다. 그래서 프로세스는 **원인을 로그에
  남기고 다시 던져서(비정상 종료 코드)** supervisor가 재시작 여부를 판단하게 한다.
- 창(pywebview)의 JS 콘솔도 평소엔 안 보인다 → UI는 에러를 **화면에 텍스트로**
  보여줘야 한다.

## 2. 계층별 현재 방식

### 2.1 프로세스 수명 (recorder / hub / desktop)

| 상황 | 처리 | 위치 |
| --- | --- | --- |
| 이미 실행 중 | `AlreadyRunningError`(전용 타입)를 잡아 `EXIT_ALREADY_RUNNING(3)`으로 종료 | `supervision/lock.py`, 각 `__main__` |
| 인자 오류 | argparse가 `EXIT_ARGUMENT_ERROR(2)`로 종료 | 각 `__main__` |
| 예기치 못한 예외 | `logger.exception`으로 남기고 **다시 raise** → 비정상 종료 코드 | `recorder/__main__.py` |
| DB를 못 엶 | 틱 루프 바깥이라 별도 `except`로 로그를 남기고 raise | `recorder/__main__.py` |

`AlreadyRunningError`를 `RuntimeError` 대신 전용 타입으로 둔 이유: `RuntimeError`로
잡으면 `NotImplementedError` 같은 전혀 다른 원인까지 "이미 실행 중"으로 오인한다.
**규칙: 의미가 있는 실패는 전용 예외 타입 + 전용 종료 코드로 구분한다.**

종료 코드는 지금 앱마다 따로 상수로 정의돼 있다(recorder, hub 각각
`EXIT_ARGUMENT_ERROR=2`, `EXIT_ALREADY_RUNNING=3`). 값이 같은 건 우연이 아니라
관례인데 코드에서 강제되지는 않는다 → 공통화 후보 (4절).

### 2.2 재시작 정책 (supervisor)

`packages/supervision/supervisor.py`의 `supervise()`가 자식 프로세스를 재시작한다.

- 호출부가 `classify_exit(exit_code)`를 넘긴다. 문자열(멈출 사유)을 돌려주면 재시작
  없이 멈추고, `None`이면 크래시로 보고 재시작한다. "어떤 코드가 재시도해도 안 풀리는
  상황인지"는 앱마다 달라서 콜백으로 뺐다.
- `classify_exit`로 못 거르는 영구 장애(디스크 가득, DB 손상)는 **크래시 루프 감지**로
  막는다: 60초(`MIN_STABLE_RUN_SECONDS`)도 못 버티고 5번(`MAX_CONSECUTIVE_FAILURES`)
  연속 죽으면 재시작을 멈춘다. 60초 이상 버틴 뒤 죽으면 카운트를 리셋한다.
- 재시작 사이에 5초 대기, 중지 요청(`stop_event`)을 받으면 `terminate()` 후 5초 안에
  안 죽으면 `kill()`(좀비가 포트/lock을 쥐지 않게).

### 2.3 로깅

`packages/supervision/log_setup.py`의 `configure_logging(logger, path)`:
`RotatingFileHandler`(1MB × 백업 3개) + 콘솔이 있을 때만 콘솔 핸들러. 프로세스마다
**로그 파일을 따로** 둔다(`recorder.log`, `supervisor.log`, `hub.log`,
`hub-supervisor.log`) — 롤오버 시점에 서로 부딪히지 않게.

### 2.4 hub HTTP API

| 상황 | 응답 | 비고 |
| --- | --- | --- |
| 모르는 경로 | 404 `{"error": ...}` | |
| `start`/`end` 누락·형식·타임존·순서·길이(31일+2시간) 오류 | 400 + 사유 메시지 | `_usage_bounds`가 `ValueError`로 통일. UTC 변환의 `OverflowError`도 `ValueError`로 감싼다 |
| DB 없음/읽기 실패 (`sqlite3.Error`) | 503 + `database unavailable` | 서버 로그에는 `logger.exception`, 응답에는 내부 경로를 안 싣는다 |
| 그 외 | (처리 없음) | 아래 한계 참고 |

원칙: **입력 오류는 4xx에 이유를 적어주고, 환경 문제는 5xx에 일반 메시지만** 준다.
검증은 `ValueError`를 던지는 함수 하나로 모으고 핸들러에서 한 번만 변환한다.

### 2.5 desktop (pywebview)

- `--dev`에서 Vite dev server가 없으면: stderr가 `None`일 수 있어 **창 안에 같은
  안내 HTML**을 띄우고 종료한다.
- hub 준비 대기 타임아웃: 예외를 던지면 창이 아예 안 떠서 사용자가 아무것도 못
  본다. 그래서 `hub-supervisor.log`에만 남기고 **창은 연다** — 이후 UI가 fetch 실패를
  화면에 보여준다. (실패를 UI 쪽으로 넘기는 설계)
- hub supervisor는 daemon 스레드로 돌고, 창이 닫히면 `stop_event`로 정리한다.

### 2.6 apps/ui

- `fetchUsage`: `!response.ok`이면 `Error("HTTP <status>")`를 던진다. 서버가 400에
  준 사유 메시지(`error` 필드)는 **아직 화면에 안 쓴다** (4절).
- `UsagePage.load`:
  - 사용자가 일으킨 로드(구간 이동 등) 실패 → `ErrorView`(메시지 + 다시 시도 버튼).
  - **백그라운드 15초 갱신 실패 → 화면을 건드리지 않는다.** 이미 잘 보여주던 데이터를
    일시적 오류(hub 재시작 중 등)로 에러 화면으로 덮지 않고 다음 주기에 다시 시도한다.
  - 응답 순서 꼬임: `latestRequestId`로 마지막 요청의 응답만 그린다.
  - 백그라운드 갱신은 진행 중인 요청이 있으면 시작하지 않는다(`inFlight`) — 느린
    응답이 계속 stale로 버려지는 걸 막는다.

## 3. 공통 원칙 (언어와 무관)

1. **조용히 삼키지 않는다.** 잡았으면 로그/화면 중 하나에는 반드시 남긴다.
2. **복구 가능성으로 나눈다.** 재시도해도 안 풀리는 것(인자 오류, 이미 실행 중)은
   전용 종료 코드/타입으로 구분해 재시작하지 않고, 나머지는 크래시로 보고 재시작하되
   루프는 감지해 멈춘다.
3. **죽는 쪽은 원인을 남기고 다시 던진다.** 로그만 하고 삼키면 supervisor가 정상
   종료로 오인한다.
4. **갱신성 실패와 사용자 요청 실패를 구분한다.** 백그라운드 새로고침은 조용히
   넘어가고, 사용자가 일으킨 동작의 실패는 화면에 알린다.
5. **외부에 주는 에러에는 내부 정보를 싣지 않는다.** 경로·스택은 로그에만.
6. **검증은 한 곳에서.** 입력 검증은 한 함수가 한 종류의 예외로 통일해 던지고, 변환
   (HTTP 400 등)은 경계에서 한 번만 한다.

## 4. 한계와 공통화 후보 (나중에 손볼 곳)

- **종료 코드 상수 중복**: recorder/hub가 각자 정의하고 desktop이 hub 것을 import한다.
  `supervision`에 `ExitCode`(예: `ARGUMENT_ERROR=2`, `ALREADY_RUNNING=3`)를 두고 공유하면
  "관례"가 코드로 강제된다. `classify_exit`의 공통 기본 구현도 같이 둘 수 있다.
- **hub의 처리되지 않는 예외**: `do_GET`에서 `ValueError`/`sqlite3.Error` 외의 예외는
  `BaseHTTPRequestHandler`가 연결을 끊어버려 UI에는 연결 오류로 보인다. 최상위에서
  `logger.exception` + 500을 주는 안전망이 필요하다.
- **API 에러 응답 규격**: 지금은 `{"error": "문자열"}`뿐이다. 코드(`code`)를 넣으면
  UI가 메시지 문자열 대신 코드로 분기·번역할 수 있다. 언어가 늘어나면(다른 클라이언트)
  특히 필요하다.
- **UI가 서버 사유를 못 보여줌**: `fetchUsage`가 응답 본문의 `error`를 읽어
  `Error` 메시지에 싣게 하면 400의 이유가 화면에 나온다.
- **fetch 타임아웃 없음**: 응답이 영영 안 오면 `inFlight`가 줄지 않아 백그라운드 갱신이
  멈춘다. `AbortSignal.timeout`을 걸면 해결된다.
- **로깅 설정은 Python 전용**: UI의 에러는 화면에만 있고 어디에도 안 남는다
  (pywebview 환경). 필요해지면 UI → hub로 에러를 보내는 엔드포인트나 pywebview의
  Python 브리지로 `hub.log`에 합치는 방법이 있다.
- **언어별 적용 시**: 원칙(3절)은 그대로 두고 표현만 바꾼다 — 종료 코드/전용 예외 타입
  → (TS) 전용 `Error` 서브클래스나 결과 타입, 로그 파일 → 해당 런타임의 로거. 공통
  규격으로 빼기 좋은 건 **종료 코드 표, API 에러 응답 형식, 재시작·크래시 루프 상수**다.
