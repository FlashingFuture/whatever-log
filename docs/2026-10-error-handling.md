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

종료 코드는 `packages/common/exit_codes.py`에 한 번만 정의하고 recorder, hub,
desktop이 import한다(`EXIT_ARGUMENT_ERROR=2`, `EXIT_ALREADY_RUNNING=3`). 예전엔
앱마다 상수를 따로 두고 값이 같기를 관례로만 맞췄고, desktop은 hub 모듈에서
가져왔다. 특정 앱에서만 의미 있는 종료 코드는 `common`에 넣지 않고 그 앱
디렉터리에서 정의한다(4 이상을 써서 겹치지 않게).

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
| 모르는 경로 | 404 `not_found` | |
| `start`/`end` 누락·형식·타임존·순서·길이(31일+2시간) 오류 | 400 `invalid_request` + 사유 메시지 | `_usage_bounds`가 `ValueError`로 통일. UTC 변환의 `OverflowError`도 `ValueError`로 감싼다 |
| DB 없음/읽기 실패 (`sqlite3.Error`) | 503 `unavailable` | 서버 로그에는 `logger.exception`, 응답에는 내부 경로를 안 싣는다 |
| 그 외 | (처리 없음) | 아래 한계 참고 |

모든 에러 응답 본문은 `packages/common/api_error.py`의 형식이다:

```json
{"error": {"code": "invalid_request", "message": "start와 end가 모두 필요합니다."}}
```

`code`는 클라이언트가 분기·번역에 쓰는 안정적인 식별자(`invalid_request`,
`not_found`, `unavailable`, `internal`), `message`는 사람이 읽는 설명이다. 특정
엔드포인트에서만 쓰는 코드는 `common`에 넣지 않고 그 앱에서 정의한다.

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

- `fetchUsage`: `!response.ok`이면 응답 본문의 `error.code/message`를 읽어
  `ApiError`(status, code, message)로 던진다. 본문이 JSON이 아니면 `HTTP <status>`.
  `ErrorView`에는 이 메시지가 그대로 나온다. 형식 선언은 `api.ts`에 따로 있다
  (TypeScript라 Python 정의를 import할 수 없다 — 형식을 바꾸면 양쪽을 같이 고친다).
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

- **`classify_exit` 공통 기본 구현**: recorder와 desktop이 거의 같은 함수를 따로
  갖고 있다. 종료 코드는 이제 `common`에 있으니 기본 구현도 `common`(또는
  `supervision`)으로 뺄 수 있다.
- **hub의 처리되지 않는 예외**: `do_GET`에서 `ValueError`/`sqlite3.Error` 외의 예외는
  `BaseHTTPRequestHandler`가 연결을 끊어버려 UI에는 연결 오류로 보인다. 최상위에서
  `logger.exception` + 500을 주는 안전망이 필요하다.
- **UI가 `code`로 분기하지는 않음**: 지금은 `message`만 보여준다. 코드별 안내문구나
  번역이 필요해지면 `ApiError.code`로 분기한다.
- **형식 선언이 언어별로 두 벌**: Python(`common/api_error.py`)과 TS(`api.ts`). 클라이언트가
  늘면 JSON Schema 같은 언어 중립 정의에서 생성하는 쪽을 검토한다.
- **fetch 타임아웃 없음**: 응답이 영영 안 오면 `inFlight`가 줄지 않아 백그라운드 갱신이
  멈춘다. `AbortSignal.timeout`을 걸면 해결된다.
- **로깅 설정은 Python 전용**: UI의 에러는 화면에만 있고 어디에도 안 남는다
  (pywebview 환경). 필요해지면 UI → hub로 에러를 보내는 엔드포인트나 pywebview의
  Python 브리지로 `hub.log`에 합치는 방법이 있다.
- **언어별 적용 시**: 원칙(3절)은 그대로 두고 표현만 바꾼다 — 종료 코드/전용 예외 타입
  → (TS) 전용 `Error` 서브클래스나 결과 타입, 로그 파일 → 해당 런타임의 로거. 공통
  규격으로 빼기 좋은 건 **종료 코드 표, API 에러 응답 형식, 재시작·크래시 루프 상수**다.
