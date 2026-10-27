# 집계/조회 API 구조: 중앙 관리소(apps/hub)

## 배경

"오늘 사용 현황" 조회 화면을 만들면서, `apps/ui`(webview 안의 TS 코드)가 recorder.db의
집계 결과를 어떻게 받아올지 정해야 했다. 후보 세 가지를 비교했다:

1. **recorder에 API 부착** — 수집 루프를 돌리는 그 프로세스가 조회 API도 서빙
2. **중앙 관리소(별도 서비스)** — recorder/UI와 독립된 제3의 프로세스가 집계/조회 전담 (채택)
3. **webview(apps/desktop)가 직접 조회** — 지금 떠 있는 데스크톱 셸이 recorder.db를 직접 읽음

①은 recorder의 유일한 책무(절대 안 죽고 계속 기록하는 것)에 조회라는 다른 책무를 얹는
것이라 기각했다 — 무거운 집계 쿼리가 수집 루프를 지연시키거나 죽이면 데이터 유실로
직결된다. ③은 지금 당장은 제일 간단하지만, 창 생명주기와 데이터 조회 책임이 한
프로세스에 묶여서 나중에 "창 없이도 동작해야 하는 기능"(AI 요약 배치 등)이 생기면
다시 쪼개야 한다.

**②를 선택**했다 — recorder/UI 둘 다 건드리지 않고, 집계·조회(그리고 나중엔 요약)를
전담하는 별도 프로세스를 둔다.

## 구조

```
apps/
├─ recorder/   # 수집 — hub를 전혀 모름
├─ hub/        # 신규: 중앙 관리소. recorder.db를 읽기 전용으로 열어 HTTP JSON API로 서빙
├─ ui/         # 조회 화면 (Vite+TS) — hub의 /api/*를 fetch
└─ desktop/    # 네이티브 창 셸 — 창을 열기 전에 hub를 자식 프로세스로 띄우고, 창이
                 닫히면 같이 종료시킨다
packages/
├─ aggregation/ # 신규: 집계 쿼리(순수 함수). recorder의 open_db()/스키마를 그대로 재사용
├─ summary/     # 신규: AI 요약 — 폴더 구조만 (Phase 3, 구현 없음)
└─ supervision/ # 신규: 중복 실행을 막는 lock + 자식 프로세스를 감시/재시작하는 supervisor
```

- `apps/hub`가 뜨고 죽는 건 `apps/desktop`(창)의 생명주기에 묶여 있다 — 창이 열려 있을
  때만 조회가 필요하므로, 상시 실행 프로세스로 둘 이유가 없다.
- 집계 쿼리 로직은 `packages/aggregation`에 따로 둬서, hub가 아닌 다른 소비자(예:
  나중의 summary 배치 작업)가 생겨도 재사용할 수 있게 했다.
- `aggregation`은 recorder의 `open_db()`를 그대로 가져다 쓴다 — 스키마를 중복 정의하면
  recorder 쪽 스키마가 바뀔 때 조용히 어긋날 수 있다.

## CORS가 실제로 적용되는 경우

`apps/ui`는 `apps/desktop`이 서빙하는 포트에서 뜨고, `apps/hub`는 다른 포트에서 뜬다 —
둘이 다른 origin이라 `fetch()`가 **실제로** cross-origin 요청이 된다(이전에 다뤘던
file:// 이슈와는 다른, 진짜로 적용되는 CORS 사례). `apps/hub`가 모든 응답에
`Access-Control-Allow-Origin: *`를 붙여서 허용한다 — 둘 다 127.0.0.1에서만 뜨는
개인용 로컬 앱이라 와일드카드로 허용해도 위험이 없다.

## uv workspace로 전환

`aggregation`이 `recorder`를 가져다 쓰고, `hub`가 `aggregation`과 `recorder`를, `desktop`이
`hub`를 가져다 쓰면서, 앱마다 독립된 `.venv`로는 서로를 import할 수 없게 됐다. pnpm이
`apps/*`/`packages/*`를 워크스페이스로 묶는 것과 같은 방식으로, 루트에 `pyproject.toml`을
추가해 `[tool.uv.workspace]`로 Python 쪽도 하나의 워크스페이스(하나의 `.venv`, 하나의
`uv.lock`)로 묶었다. 기존에 `apps/recorder`, `apps/desktop`에 따로 있던 `.venv`/`uv.lock`은
지웠다 — 이제 루트에서 `uv sync` 한 번으로 전체가 설치된다. `uv run python -m recorder` 같은
기존 사용법은 그대로 동작한다(uv가 가장 가까운 워크스페이스 루트를 찾아서 공유 `.venv`를
쓴다).

여러 앱의 `tests/test_main.py`처럼 파일명이 겹치는 경우를 대비해, 루트
`pyproject.toml`에 `--import-mode=importlib`를 설정해뒀다(각 앱 디렉터리 안에서
`uv run pytest`로 그 앱만 돌릴 때는 그 앱의 `pyproject.toml`이 더 가까운 설정이라
무관하게 동작한다).

## summary는 폴더 구조만

`packages/summary`는 Phase 3(README 로드맵)에서 구현한다. 지금은 `src/summary/__init__.py`에
의도만 적어두고 실제 코드는 없다 — "필요할 때 추가" 원칙에 따라, 다른 코드가 이 패키지의
존재를 전제로 설계될 수 있을 정도로만 자리를 잡아뒀다.

## apps/desktop가 hub를 띄우는 건 SRP 위반이 아니다 — 그리고 lock+supervisor를 공통화한 이유

`apps/desktop`가 hub를 자식 프로세스로 띄우고 감시하는 건, hub의 **역할(집계/쿼리)**을
가져온 게 아니라 **생명주기**만 관리하는 것이다 — desktop 코드에는 DB를 읽거나 집계하는
코드가 전혀 없다. 이건 Electron의 main process가 sidecar 프로세스를 띄우는 것과 같은,
"진입점이 자기가 필요한 의존 프로세스를 띄운다"는 흔한 패턴이라 SRP 위반으로 보지
않는다.

다만 이 선택에는 실질적인 약점이 있었다:

- **크래시 복원력 없음**: desktop이 강제로 죽으면(SIGKILL 등) 정리 코드가 못 돌아서 hub가
  좀비로 남을 수 있다.
- **포트 충돌 처리 없음**: hub가 이미 떠 있는 상태(좀비 등)에서 desktop을 다시 켜면,
  새 hub는 포트 바인딩 실패라는 원인을 알기 어려운 에러로 죽는다.

recorder가 이미 lock(`AlreadyRunningError`)과 supervisor(재시작 + 크래시 루프 포기)로 같은
문제를 풀어뒀다 — hub도 똑같은 모양의 문제라, 복제하는 대신 `packages/supervision`으로
빼서 둘 다 쓰게 했다:

- `supervision.lock`: recorder의 `lock.py`를 그대로 옮겼다. 처음부터 recorder 전용 로직이
  전혀 없는 순수 인프라였다. hub가 `main()`에서 포트별 lock(`hub-<port>.lock`)을 잡아서,
  중복 실행을 "포트 바인딩 실패"가 아니라 명확한 "이미 실행 중"으로 감지한다.
- `supervision.log_setup`: 역시 recorder 전용 로직이 없던 순수 인프라. hub도 콘솔 없이
  (desktop의 자식 프로세스로) 뜨므로 파일 로그가 필요해서 같이 뺐다.
- `supervision.supervisor`: 자식 프로세스를 띄우고, 비정상 종료하면 재시작하되 크래시
  루프는 포기하는 메커니즘(recorder의 `supervisor.py`에 있던 것)을 일반화했다. "어떤
  종료 코드가 재시도해도 안 풀리는 상황인지"는 호출부마다 다르므로(recorder는
  `EXIT_ARGUMENT_ERROR`/`EXIT_ALREADY_RUNNING`, hub도 같은 패턴이지만 별개의 상수) 콜백
  (`classify_exit`)으로 받는다.
  - desktop은 hub를 **창이 떠 있는 동안만** 감시해야 해서(recorder처럼 "영원히"가 아님),
    `supervise()`에 `stop_event`를 추가했다 — 창이 닫히면 desktop이 이벤트를 set해서,
    떠 있는 hub를 종료시키고 더 재시작하지 않고 바로 리턴하게 한다. recorder는 이
    인자를 안 넘기므로 기존 동작(영원히 감시)에 영향이 없다.

recorder의 `supervisor.py`/`healthcheck.py`/`__main__.py`도 이 공통 모듈을 쓰도록
고쳤다 — 복제된 두 번째 사본을 남겨두면 한쪽만 고치고 잊어버리는 drift가 생기기
쉽다.

## 타입(인터페이스)을 패키지에서 관리하는 구조

`aggregation`/`hub`는 같은 언어(Python)라 공유 타입을 안 쓸 이유가 없어서, `today_usage()`의
반환 모양을 `TypedDict`(`ProcessUsage`, `TodayUsage`)로 `packages/aggregation`에 정의해뒀다.
`apps/ui`(TS)는 언어 경계를 넘어가므로 지금은 독립된 `interface`를 유지한다 — 엔드포인트가
하나뿐인 지금 JSON Schema/codegen 같은 인프라를 들이는 건 과한 선투자라고 보고, 엔드포인트가
늘어나거나 모양이 복잡해지면 그때 공유 스펙을 두는 걸 고려한다.
