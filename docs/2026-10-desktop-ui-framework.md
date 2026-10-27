# 데스크톱 UI 프레임워크: Vite + pywebview

## 배경

CLAUDE.md "아직 정해지지 않은 것"에 있던 데스크톱 앱 프레임워크 선택을 이 문서로 확정한다.
Electron/Tauri/pywebview/네이티브 Python GUI를 비교했고, 아래 이유로 **Vite(프론트) +
pywebview(네이티브 창 셸)** 조합을 고른다.

## 비교했던 선택지

| 선택지 | 장점 | 단점 |
|---|---|---|
| Electron + Vite | 생태계·문서 제일 풍부 | Chromium+Node 통째로 번들(설치 파일 100MB+), npm 의존성 트리가 커서 공급망 노출이 큼 |
| Tauri + Vite | OS 네이티브 webview라 바이너리 작음 | Rust 툴체인을 새로 들여야 함 ("필요할 때 추가" 원칙과 충돌) |
| pywebview + Vite | 새 런타임 없이 기존 Python/uv 스택 재사용, OS 네이티브 webview(Windows=WebView2)라 가벼움 | pywebview 생태계가 Electron보다 작음 |
| Python GUI (PyQt 등) | 의존성 최소 | 타임라인/그래프 중심 UI를 웹 차트 생태계 없이 만들기 번거로움 |

## 이 프로젝트와의 적합성

- **스택 재사용**: recorder가 이미 Python/uv로 SQLite를 다루고 있다. pywebview도 같은
  Python/uv 스택이라 새 런타임(Node 런타임을 앱 안에 내장하는 것, 또는 Rust)을 들이지
  않고 "창을 띄우고 로컬 webview로 보여주는" 역할만 얇게 추가한다.
- **공급망 노출 최소화**: 지난 Node.js/pnpm 버전 점검(`docs/2026-10-nodejs-pnpm-version-upgrade.md`)에서
  "UI 프레임워크를 들이는 순간 npm 의존성 트리가 커진다"고 짚었다. Electron은 자체가 큰
  의존성이고 electron-builder 등 빌드 체인도 무겁다. pywebview는 OS가 이미 가진
  WebView2(Windows)를 그대로 쓰므로 Chromium을 따로 묶어 배포하지 않는다.
- **역할별 분리**: recorder(수집)와 데스크톱 셸(창 띄우기)은 둘 다 Python이지만 서로 다른
  앱(`apps/recorder`, `apps/desktop`)으로 분리한다. 실제 UI 코드(TS/HTML/CSS)는 `apps/ui`에
  별도로 두고, 셸은 그걸 보여주는 창일 뿐 UI 내부를 모른다 — 나중에 Electron/Tauri로
  셸만 바꿔도 `apps/ui`는 그대로 쓸 수 있다.
- **데이터 접근**: recorder가 SQLite를 WAL 모드로 쓰고 있어서 동시 읽기가 안전하다. 집계
  쿼리는 Python 쪽(`apps/ui`가 호출할 API든, pywebview 셸이 직접 읽든)에서 recorder와
  같은 방식으로 처리할 수 있어 "집계" 책임을 어디 둘지 고민이 줄어든다.

## 구조

```
apps/
├─ recorder/   # 기존: 수집 (Python/uv)
├─ ui/         # 신규: 조회 화면 (Vite + TS, pnpm 워크스페이스 멤버)
└─ desktop/    # 신규: 네이티브 창 셸 (Python/uv, pywebview)
                 개발 중엔 Vite dev server(http://localhost:5173)를 열고,
                 빌드 후엔 apps/ui/dist를 로컬 HTTP(127.0.0.1)로 띄워서 연다.
```

빌드 결과를 `file://`로 직접 열지 않는 이유: Chromium 계열 엔진은 `<script type="module">`을
`fetch()`로 로드하는데, `fetch()`의 `file://` 접근 자체를 막아둬서 코드가 여러 청크로
쪼개지면(동적 import 등) 화면이 안 뜰 수 있다. 지금처럼 번들이 파일 하나뿐이면 당장은
재현되지 않지만, 화면이 복잡해지기 전에 `apps/desktop`이 임시 로컬 HTTP 서버(데몬 스레드,
127.0.0.1에만 바인딩)로 `dist`를 서빙하도록 미리 막아뒀다.

`ui`와 `desktop`을 같은 폴더에 두지 않은 이유: pnpm 워크스페이스는 `apps/*` 바로 아래의
`package.json`만 멤버로 잡고, Python 쪽은 `src/<패키지명>` 레이아웃(recorder와 동일)을
쓰는데 Vite도 기본적으로 `src/`를 쓴다 — 한 폴더에 섞으면 `src/`가 TS/Python 양쪽 의미로
충돌한다. 두 앱으로 나누면 각자 자기 툴체인(pnpm/uv)의 관습을 그대로 따를 수 있다.

## 프레임워크(React/Svelte 등) 선택은 미룬다

`apps/ui`는 일단 Vite의 vanilla-ts 템플릿으로 시작한다. 지금은 Vite+pywebview 연결 자체를
검증하는 게 목적이고, 화면 복잡도가 실제로 늘어날 때(목표·캘린더, 타임라인 차트 등) 그때
필요한 프레임워크를 고른다 ("필요할 때 추가").
