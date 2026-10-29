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
file:// 이슈와는 다른, 진짜로 적용되는 CORS 사례).

처음엔 `Access-Control-Allow-Origin: *`로 전부 허용했는데, 이건 "127.0.0.1에만
바인딩했으니 안전하다"는 잘못된 가정이었다 — 와일드카드를 열면 사용자가 띄워둔
**아무 웹사이트나** 이 API를 fetch해서 프로세스별 사용 시간(개인 활동 정보)을
읽어갈 수 있다. 브라우저의 로컬 네트워크 접근 제한에 기대는 것도 위험하다. 지금은
요청의 `Origin`이 `http://(127.0.0.1|localhost)(:포트)?` 패턴일 때만 그 origin을
그대로 반사하고 `Vary: Origin`을 같이 보낸다 — desktop이 서빙하는 UI(임의 포트)와
Vite dev server(5173) 둘 다 이 패턴에 맞는다.

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

`aggregation`/`hub`는 같은 언어(Python)라 공유 타입을 안 쓸 이유가 없어서, 집계 함수의
반환 모양을 `TypedDict`(`ProcessUsage`, `RangeUsage`)로 `packages/aggregation`에 정의해뒀다.
`apps/ui`(TS)는 언어 경계를 넘어가므로 지금은 독립된 `interface`를 유지한다 — 엔드포인트가
하나뿐인 지금 JSON Schema/codegen 같은 인프라를 들이는 건 과한 선투자라고 보고, 엔드포인트가
늘어나거나 모양이 복잡해지면 그때 공유 스펙을 두는 걸 고려한다.

## 코드리뷰로 추가로 고친 것들

- **hub의 DB 연결을 읽기 전용(`mode=ro`)으로**: `recorder.storage.open_db()`는 WAL 모드를
  설정하고 스키마가 없으면 만드는, 쓰기 가능한 연결이다. hub는 조회만 하는 쪽이므로 이
  연결을 열어둘 이유가 없었다. 지금은 `sqlite3.connect(..., uri=True)`로 읽기 전용 연결을
  열고, DB가 아직 없거나(recorder가 한 번도 안 돈 경우) 읽기 중 문제가 생기면 응답 없이
  연결이 끊기는 대신 503으로 알린다. `apps/ui`도 `response.ok`를 확인하지 않으면 503의
  에러 바디를 `TodayUsage`인 것처럼 렌더링하려다 깨지므로 같이 고쳤다.
- **desktop이 hub 대기 시간 초과를 삼키지 않도록**: `_wait_for_hub_port`가 타임아웃을
  던지면 `webview.create_window`가 전혀 호출되지 않아 창이 안 뜨고, `pythonw.exe`
  환경이라 traceback도 안 보여서 사용자는 아무것도 못 봤다. 지금은 타임아웃을
  `hub_supervisor_logger`에만 남기고 창은 그대로 연다 — `apps/ui`가 fetch 실패를
  감지해서 화면에 에러로 보여준다.
- **supervise()의 강제 종료 경로**: `stop_event`가 set됐을 때 `process.terminate()` 후
  `process.wait(timeout=5)`가 `TimeoutExpired`를 던지면(멈춰 있는 프로세스 등) 예외가
  `supervise()` 밖으로 전파돼서, 종료되지 않은 hub가 포트/lock을 계속 쥔 채로 좀비가
  되고 다음 실행이 `EXIT_ALREADY_RUNNING`으로 막혀버렸다. `TimeoutExpired`를 잡아서
  `kill()`로 강제 종료하도록 고쳤다.
- **일광절약시간 전환일의 자정 경계**: `_local_day_bounds_utc`가 `now.astimezone()`의
  tzinfo(조회 시점의 고정 UTC 오프셋)를 자정/다음 자정에 그대로 재사용해서, 오프셋이
  바뀌는 전환일에 하루가 틀어질 수 있었다. 자정 경계를 naive datetime으로 만든 뒤 각자
  `astimezone(UTC)`로 변환해서, 각 시각에 맞는 오프셋을 다시 계산하게 했다(이 Windows
  dev 환경엔 `tzdata`가 없어 실제 DST 전환을 자동 테스트로 재현하진 못했다 — Python
  문서에 명시된 naive `astimezone()` 동작에 근거한 수정이다).
- **루트 `uv sync`가 workspace 멤버를 설치하지 않는다는 리뷰는 반영하지 않음**: 실제로
  `.venv`/`uv.lock`을 지우고 새로 `uv sync`를 돌려봤는데, 루트 `pyproject.toml`에
  `[project]`가 없는 "virtual workspace root"라서 기본 동작으로 전체 멤버가 설치됐다
  (`uv run pytest`도 바로 통과). 리뷰가 가정한 문제는 루트에 `[project]`가 있는
  워크스페이스에서나 해당하는 것으로 보인다.

## "오늘" 한 줄 요약에서 "최근 24시간" 막대 차트로

> 이 절의 `range=24h`와 "최근 24시간" 결정은 아래 "일/주/월 단위 탐색으로"에서
> 바뀌었다. 세 버킷(active/idle/background) 설명은 그대로 유효하다.

`today_usage()`(로컬 오늘, foreground 시간만)를 `packages/aggregation/src/aggregation/range.py`의
`usage_by_range(conn, start, end)`로 대체했다 — 임의의 `[start, end)` UTC 구간을 받는
범용 함수로 일반화해서, 나중에 기간 선택 UI가 붙어도 그대로 재사용할 수 있게 했다.
hub는 지금 `range=24h`(최근 24시간, rolling) 하나만 지원하고(`/api/usage?range=24h`),
모르는 값은 400으로 거부한다 — 기간 선택 UI가 올 자리를 명시적으로 남겨둔 것이다.

집계 결과도 필드 하나(`seconds`)에서 세 개로 늘었다 — 처음엔 active/total
두 개였는데, idle 시간이 "total에서 active를 뺀 나머지"에 background 시간과
뭉쳐 들어가서 화면에서 둘을 구분할 수 없었다. 틱마다 열려 있던 프로세스를
겹치지 않는 세 버킷 중 정확히 하나로 분류하도록 다시 나눴다
(`active_seconds + idle_seconds + background_seconds == total_seconds`):

- `active_seconds`: foreground였고 동시에 idle(90초 이상 입력 없음, 자세한 건
  `docs/2026-10-idle-threshold.md`)이 아니었던 시간.
- `idle_seconds`: foreground였지만 idle이었던 시간.
- `background_seconds`: foreground가 아니었지만 창이 떠 있던(background) 시간
  (`tick_windowed_processes` 기반). 여러 프로세스가 동시에 떠 있으면 같은
  구간이 각자에게 중복으로 더해진다(서로 다른 프로세스의 "열려 있던 시간"이라
  겹치는 게 맞다 — 모든 프로세스의 `background_seconds`를 그냥 더하면 실제
  경과 시간보다 커질 수 있다는 뜻이기도 하다).

"UTC 오늘"과 "로컬 오늘" 중 하나를 고르는 대신 "최근 24시간"을 택한 이유: UTC
오늘은 한국 시간(UTC+9) 기준 자정이 아니라 오전 9시에 날짜가 바뀌어서 사용자
체감과 안 맞고, 로컬 오늘은 타임존/DST 경계 처리가 또 필요하다(이미 한 번 버그를
냈던 부분). 최근 24시간은 그런 경계 계산이 전혀 필요 없다.

## apps/ui를 컴포넌트로 구조화

`apps/ui/src`를 한 파일(`main.ts`)에 다 때려넣는 대신 역할별로 나눴다:

```
apps/ui/src/
├─ api.ts                     # hub fetch + 타입(ProcessUsage, RangeUsage)
├─ period.ts                  # 일/주/월 구간 계산(순수 함수, DOM 없음)
├─ theme.ts                   # 색상 토큰
├─ styles/injectStyle.ts      # <style> 태그 1회 주입 헬퍼
├─ components/
│  ├─ UsagePage.ts            # 화면 전체: 상태(보고 있는 구간) + 조합
│  ├─ PeriodNavigator.ts      # "← 라벨 →" 구간 이동(단위와 무관)
│  ├─ SegmentedControl.ts     # 여러 값 중 하나 고르기(값 종류와 무관)
│  ├─ Button.ts               # 위 둘과 ErrorView가 같이 쓰는 버튼
│  ├─ UsageChart.ts           # 범례 + 막대 목록
│  ├─ BarRow.ts               # 프로세스 한 줄(라벨 + 3색 막대 + 값)
│  └─ ErrorView.ts            # 에러 + 다시 시도 버튼
└─ main.ts                    # 진입점: 전역 스타일 + UsagePage 마운트
apps/ui/tests/period.test.ts  # Node 내장 테스트 러너(`pnpm --filter ui test`)
```

`PeriodNavigator`/`SegmentedControl`/`Button`은 "사용 현황"이라는 걸 모른다 — 라벨과
콜백만 받는다. 상태와 "무엇을 보여줄지"는 `UsagePage` 한 곳에만 있다.

CSS는 별도 `.css` 파일 대신, 각 컴포넌트 파일이 자기 스타일을 `injectStyle(id,
css템플릿)`로 직접 들고 있다 — styled-components 같은 라이브러리(빌드 플러그인
필요)는 안 들이고, "컴포넌트 파일 안에 그 컴포넌트의 스타일을 같이 둔다"는
정도로 가볍게 흉내만 냈다. 모듈이 import될 때 한 번 `<style>` 태그를 넣고,
이미 넣은 id면 다시 안 넣는다.

색 테마는 연한 파란색(`active`) 하나만 포인트로 쓰고 나머지는 흑백/회색 — 막대는
`bar-fill`(이 프로세스의 total_seconds만큼 폭) 안에 active/idle/background
세 구간을 겹치지 않게 나란히 채운다(`display: flex`, 각 구간 폭은 그 버킷/total
비율).

## "최근 24시간"에서 일/주/월 단위 탐색으로

날짜 라벨을 띄우고 ←/→로 하루·한 주·한 달씩 넘기게 하면서, 위에서 택했던
"최근 24시간(rolling)"은 버렸다 — "10월 28일"이라고 써놓고 그 범위가 어제 오후
3시~오늘 오후 3시이면 라벨과 실제가 어긋난다. 구간은 사용자 달력 기준이어야
한다(로컬 자정, 월요일 시작, 1일).

예전에 로컬 경계를 피했던 건 Python에서 타임존/일광절약시간을 계산하다 버그를
냈기 때문이다. 그래서 경계 계산 자체를 `apps/ui/src/period.ts`(브라우저)로 옮겼다 —
`new Date(y, m, d)`가 로컬 자정을 만들고 일광절약시간 전환도 처리한다. hub는 계산된
경계를 받기만 한다:

- `/api/usage?start=...&end=...` — 타임존이 붙은 ISO 8601. ui는 `toISOString()`("Z"
  표기)으로 보낸다. 오프셋의 `+`는 쿼리 문자열에서 공백으로 디코딩되기 때문이다.
- 타임존 없는 값, `start >= end`, 31일(+일광절약시간 여유 1시간) 초과는 400.
  `range=24h`는 없앴다(ui가 유일한 호출부였다).
- `usage_by_range()`는 받은 경계를 UTC로 정규화한 뒤 비교한다 — `sampled_at`이 UTC
  문자열이라 `+09:00` 경계를 그대로 비교하면 같은 시각이어도 조용히 틀린 구간이
  잡힌다.

화면 동작:

- 기본은 오늘(일 단위). 지금이 들어 있는 구간이면 →(키보드 →도)를 막고 라벨 옆에
  "오늘/이번 주/이번 달"을 붙인다.
- 단위를 바꾸면, 현재 구간을 보고 있었으면 지금을, 과거를 보고 있었으면 그 구간의
  시작을 기준으로 새 단위의 구간을 잡는다(이번 달 → 일이면 1일이 아니라 오늘).
- 15초 주기 갱신은 현재 구간을 볼 때만 한다. 자정을 넘기면 보고 있던 "오늘"이
  어제가 되므로, 주기마다 헤더를 다시 그려 →를 켜고 표시를 뗀다.
- 구간을 빠르게 넘기면 이전 요청의 응답이 늦게 올 수 있어서, 마지막으로 보낸
  요청의 응답만 그린다.

남은 것: 월 단위는 15초 간격이면 틱이 약 18만 개라, 데이터가 한 달치 쌓이면 쿼리가
지금(수십 ms)보다 훨씬 무거워질 수 있다. 실제로 느려지면 일 단위 사전 집계를
고려한다.
