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
└─ summary/     # 신규: AI 요약 — 폴더 구조만 (Phase 3, 구현 없음)
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
