# CLAUDE.md

이 파일은 README.md의 "프로젝트 방향"을 Claude가 작업할 때 지켜야 할 규칙으로 옮긴 것입니다. README는 사람을 위한 설명, 이 파일은 코드를 작성/수정할 때의 판단 기준입니다.

`docs/`는 설계 논의·검토했던 대안·히스토리를 사람이 보기 위해 남겨둔 기록입니다. 참고하지 마세요 — 결론이 바뀐 이전 논의나 폐기된 대안도 그대로 남아있어서, 최신 상태가 아닐 수 있습니다. 판단 기준은 항상 이 파일과 실제 코드입니다.

## 아키텍처 원칙

- **모노레포 구조**: `apps/`(실행 단위)와 `packages/`(재사용 단위)를 구분합니다. 새 코드를 추가하기 전에 어느 쪽에 속하는지 먼저 정하세요.
- **역할별 분리**: 수집 · 저장 · 집계 · 요약 · UI는 서로의 내부 구현을 몰라도 동작해야 합니다. 레이어를 건너뛰어 직접 의존하는 코드를 만들지 마세요.
- **교체 가능한 구성 요소**: 저장소, AI 제공자(외부 API / 로컬 모델), 수집 방식은 인터페이스 뒤에 둡니다. 특정 구현에 직접 결합된 코드를 작성하지 마세요.
- **필요할 때 추가**: 지금 쓰이지 않는 기능·추상화·설정 옵션을 미리 만들지 않습니다. 로드맵에 없는 범위를 선제적으로 구현하지 마세요.

## 코드 스타일

- 영리한 코드보다 읽히는 코드를 택합니다.
- 이름만 보고 역할을 알 수 있게 짓습니다.
- 디렉터리 구조만 봐도 흐름이 보이도록 파일을 배치합니다.
- **함수 docstring/주석**: 내부 함수(이름이 `_`로 시작)나 아주 단순한 함수(한두 줄,
  보자마자 역할이 보임)가 아니면, 한 줄 이상으로 **그 함수의 실제 용도**를 적습니다.
  코드를 그대로 되풀이하는 설명이 아니라 "왜/무엇을 위해 쓰는지"를 적으세요.
  (CodeRabbit의 docstring coverage 체크 기준에도 맞춰야 합니다.)

## 로컬 우선 / 데이터 처리

- 기록 데이터는 기본적으로 사용자 기기에 저장합니다.
- 프로세스명·창 제목 등 민감한 기록을 외부 서비스(AI API 포함)로 보내는 코드를 추가할 때는 그 사실을 사용자에게 알리세요. 기본값은 "외부로 보내지 않음"입니다.

## 강제되는 규칙 (hooks — advisory 아님)

- `.env`, `secrets.*` 등 민감 파일 편집은 `.claude/settings.json`의 PreToolUse hook으로 차단됩니다. 이 파일을 수정해야 하는 경우 직접 편집을 시도하지 말고 사용자에게 알리세요.
- Edit/Write 이후 PostToolUse hook이 자동으로 포매팅을 적용합니다. 별도로 포매팅 명령을 실행할 필요는 없습니다.
- 커밋 시점에는 `.husky/pre-commit`이 lint·포매팅을 최종 검증합니다. 이 단계에서 실패하면 hook을 건너뛰지 말고 원인을 고치세요.

## 개발 환경

- **패키지 매니저**: pnpm (workspace: `apps/*`, `packages/*`). `packageManager` 필드로 버전이 고정되어 있어 corepack이 자동으로 맞는 버전을 사용합니다.
- **Lint/Format**: Biome. `pnpm lint`(검사) / `pnpm format`(수정). ESLint·Prettier는 쓰지 않습니다.
- **커밋 전 검증**: Husky `pre-commit` → `lint-staged`가 staged 파일에 Biome을 적용합니다.
- **커밋 메시지 본문**: 한글로 작성합니다.
- **Node**: LTS 24.x 기준 (`engines.node: ">=22.23.4"`, `lint-staged`의 실제 요구 버전 + 2026-10 Node 보안 릴리스 반영). Node 18은 2025-04 EOL이라 지원하지 않습니다.
- **Dockerfile + docker-compose.yml (루트)**: 디바이스 간 Node 버전을 동일하게 맞추기 위한 개발 컨테이너입니다. 앱을 빌드/배포하는 용도가 아닙니다. `docker compose run --rm dev bash`로 들어가서 씁니다. 빌드·실행 검증 완료 (Node/pnpm 버전이 호스트와 일치함을 확인함).
  - `node_modules`는 named volume(`node_modules`)으로 분리되어 있습니다. 호스트(Windows)와 컨테이너(Linux)는 네이티브 바이너리가 다르므로(예: `@biomejs/cli-win32-x64` vs `cli-linux-x64`) **절대 호스트의 `node_modules`를 컨테이너와 공유(bind mount)하지 마세요** — 서로의 설치를 깨뜨립니다.
  - pnpm store 위치도 `npm_config_store_dir` 환경변수로 `node_modules` volume 안쪽에 고정되어 있습니다. 이게 없으면 컨테이너의 pnpm이 store를 프로젝트 루트(호스트 bind mount)에 흘려서 `.pnpm-store/`가 커밋 대상에 섞여 들어갑니다. 이 설정을 건드릴 때는 이 사실을 기억하세요.
  - Python 등 다른 스택이 들어오면 `Dockerfile`에 추가하되, 아직 쓰이지 않는 스택을 미리 넣지 마세요.
- **mise (`.mise.toml`, 루트)**: Node 버전만 고정되어 있습니다(`node = "24.22.1"`). `engines.node`/Dockerfile의 Node 버전과 반드시 같이 맞추세요. 다른 스택(Python 등)이 들어오면 여기에도 추가.

## 아직 정해지지 않은 것

앱/패키지별 빌드·테스트 명령은 이후 Phase에서 구현하면서 채웁니다.

데스크톱 앱 프레임워크는 Vite(`apps/ui`) + pywebview(`apps/desktop`)로 정했습니다
(`docs/2026-10-desktop-ui-framework.md` 참고). `apps/ui`는 조회 화면(TS, pnpm 워크스페이스
멤버)이고, `apps/desktop`은 그걸 네이티브 창으로 띄우는 셸(Python/uv)입니다 — 두 앱으로
나눈 이유는 pnpm 워크스페이스가 `apps/*` 바로 아래 `package.json`만 멤버로 잡고, Python
쪽 src-layout 관습(`src/<패키지명>`)이 Vite의 `src/`와 한 폴더에서 충돌하기 때문입니다.

집계/조회 API는 `apps/hub`(중앙 관리소)가 전담합니다(`docs/2026-10-hub-architecture.md`
참고). recorder는 수집만, hub는 recorder.db를 읽기 전용으로 열어 집계 결과를 로컬 HTTP
API로 서빙만 합니다 — `apps/desktop`이 창을 열 때 hub를 자식 프로세스로 함께 띄웁니다.
집계 쿼리 자체는 `packages/aggregation`에 재사용 가능한 형태로 분리했습니다.
`packages/summary`(AI 요약)는 Phase 3 전까지 폴더 구조만 있고 구현은 없습니다.

Python 쪽도 pnpm workspace와 같은 방식으로 uv workspace(루트 `pyproject.toml`의
`[tool.uv.workspace]`)로 묶여 있습니다 — 여러 앱이 서로를 import하면서 앱별 독립
`.venv`로는 부족해졌기 때문입니다. `uv sync`/`uv run`은 루트에서 한 번만 하면 되고,
`apps/recorder`처럼 각 앱 디렉터리 안에서 실행해도 가장 가까운 워크스페이스 루트의
공유 `.venv`를 그대로 씁니다.
