# whatever.log

> 뭐라도 하겠지.

PC에서 실행 중인 프로세스와 활성 창을 주기적으로 기록하고, 사용자가 설정한 목표·일정과 비교해 **AI 기반 일일 요약과 목표 달성 연관성**을 제공하는 앱입니다.

> 상태: **베타** — 기록·조회·목표, Google 로그인과 목표 동기화까지 동작합니다. AI 요약과 일정(캘린더)은 아직 없습니다.

---

## 설치 (Windows)

1. [Releases](https://github.com/FlashingFuture/whatever-log/releases)에서 `whatever-log-<버전>-win64.zip`을 받습니다.
2. **옮기지 않을 곳**에 압축을 풀고 `install.cmd`를 실행합니다. 파이썬이 폴더에 들어 있어서 따로 설치할 것이 없습니다.
3. 시작 메뉴의 **whatever.log**를 엽니다. 기록기는 로그인할 때 자동으로 시작됩니다.

- **업데이트**: 새 zip을 새 폴더에 풀고 `install.cmd`를 실행합니다. 기록과 목표는 `%LOCALAPPDATA%\whatever.log`에 있어서 그대로 이어집니다.
- **제거**: 설치 폴더에서 `whatever-log.cmd uninstall`. 데이터는 지우지 않습니다(지우려면 위 폴더를 직접 지웁니다).

자세한 동작과 릴리스 절차는 [docs/packaging.md](docs/packaging.md)에 있습니다.

---

## 기능

- **기록**: 15초마다 활성 창과 창이 있는 프로세스, 입력 여부를 기록합니다. 크롬·엣지는 보고 있는 사이트(도메인)도 기록합니다.
- **조회**: 기간을 골라 앱·사이트별 사용 시간을 봅니다.
- **목표**: 목표를 만들고 앱·사이트를 연결해 목표 시간 대비 얼마나 했는지 봅니다.
- **동기화(선택)**: Google로 로그인하면 목표 목록과 기기별 달성도를 여러 PC에서 함께 씁니다. 프로세스·사이트 이름과 기록은 서버로 보내지 않습니다([docs/data-handling.md](docs/data-handling.md)).
- **예정**: 목표 관련 일정을 캘린더에 배치, AI 일일 요약과 목표 연관성 분석.

---

## 프로젝트 방향

### 1. 모노레포
기록 에이전트, 앱 UI, 공통 로직을 하나의 저장소에서 관리합니다. 실행 단위(앱)와 재사용 단위(패키지)를 나누고, 공통 타입과 규칙은 한 곳에서 정의합니다.

### 2. 확장성 있는 설계
- **역할별 분리**: 수집 · 저장 · 집계 · 요약 · UI는 서로의 내부 구현을 몰라도 동작하도록 경계를 둡니다.
- **교체 가능한 구성 요소**: 저장소, AI 제공자(외부 API / 로컬 모델), 수집 방식은 인터페이스 뒤에 두어 나중에 바꿀 수 있게 합니다.
- **필요할 때 추가**: 지금 필요하지 않은 기능과 추상화는 미리 만들지 않습니다.

### 3. 가독성 우선
- 영리한 코드보다 읽히는 코드를 택합니다.
- 이름만 보고 역할을 알 수 있게 짓습니다.
- 디렉터리 구조만 봐도 앱의 흐름이 보이게 둡니다.

### 4. 로컬 우선
기록은 기본적으로 사용자 기기에 저장하고, 민감한 정보는 외부로 보내지 않는 것을 기본값으로 합니다.

---

## 구조

```
.
├─ apps/
│  ├─ recorder/   # 기록기: 활성 창·프로세스·사이트를 SQLite에 기록
│  ├─ hub/        # 로컬 HTTP API: 집계·목표·계정을 화면에 제공
│  ├─ ui/         # 화면(Vite + TypeScript)
│  ├─ desktop/    # 화면을 띄우는 창(pywebview)
│  ├─ sync/       # 동기화 에이전트: 목표를 서버와 주기적으로 맞춤
│  ├─ launcher/   # `whatever-log` 명령: 설치·시작·종료·상태
│  └─ server/     # 서버(Cloudflare Workers + D1): 로그인, 목표 동기화
├─ packages/      # 재사용 단위: aggregation, goals, goalsync, cloud, chromium, supervision, common, summary(예정)
├─ docs/          # 설계 문서
├─ scripts/       # 릴리스 번들 만들기(build_release.py)와 설치 스크립트
└─ .github/       # CI(ci.yml)와 릴리스(release.yml)
```

---

## 로드맵

- [x] **Phase 0**: 모노레포 골격, 기본 앱 실행
- [x] **Phase 1**: 프로세스 기록과 저장, 기본 조회 화면
- [ ] **Phase 2**: 목표·캘린더, 일 단위 집계 — 목표·집계·목표 동기화는 됨, 캘린더(일정 배치)는 남음
- [ ] **Phase 3**: AI 일일 요약과 목표 연관성 분석

---

## 개발 환경

- **Python**: 3.14 (`.python-version` — uv가 읽는다. CI·릴리스 빌드와 같은 버전). [uv](https://docs.astral.sh/uv/) workspace로 묶여 있어 루트에서 `uv sync` 한 번이면 된다.
- **Node**: 24.x LTS (`package.json`의 `engines.node`, `.mise.toml` 참고)
- **패키지 매니저**: pnpm — `corepack enable` 후 `pnpm install`
- **Lint/Format**: `pnpm lint`, `pnpm format` (Biome)
- **테스트**: `uv run pytest`(파이썬 전체), `pnpm --filter ui test`, `pnpm --filter server test`. PR마다 CI(`.github/workflows/ci.yml`)가 이것들과 lint·타입 검사를 돌린다.
- **버전 관리(로컬)**: [mise](https://mise.jdx.dev/)로 Node·Python 버전을 고정해뒀습니다 (`.mise.toml`). `mise install`로 맞는 버전을 받고, `mise activate`를 쉘 프로필에 추가하면 디렉터리 진입 시 자동 전환됩니다.
- **Docker**: `docker-compose.yml` + `Dockerfile`로 개발 환경을 컨테이너화할 수 있습니다. 앱 빌드용이 아니라 여러 디바이스에서 동일한 Node 버전을 보장하는 용도입니다. `docker compose run --rm dev bash`로 들어가서 작업하면 됩니다. (빌드/실행 검증 완료) `docker compose up server`는 Cloudflare 쪽(Worker + 로컬 D1)을 `127.0.0.1:8790`에 띄워 동기화를 시험하는 용도입니다(명령과 통합 시험 방법은 `docs/sync-client.md`의 "서버를 로컬에서 띄워 통합 시험 하기").
- **저장소에서 바로 실행**: `uv sync` 뒤 `uv run whatever-log install` 한 번이면 자동 시작 등록, 시작 메뉴 바로가기, 화면 빌드까지 한다(데이터는 앱 폴더 안에 쌓인다). 자세한 명령은 `docs/packaging.md`.

## 라이선스

[MIT](LICENSE)
