# 릴리스 번들 시험 (Windows Sandbox)

릴리스 번들(`docs/packaging.md`)을 **깨끗한 윈도우**에서 설치부터 제거까지 시험하는 체크리스트다. 개발 PC에는 uv·Python·Node·기존 등록·기존 데이터가 있어서,
"처음 받은 사람이 겪는 일"은 개발 PC에서 재현되지 않는다. Windows Sandbox는 켤 때마다 새 윈도우가 뜨고 닫으면 전부 사라지므로 그 대용으로 쓴다.

개발 PC에서 이미 확인한 것(단위 테스트, 번들 내용물, 번들을 풀어 `uv sync --frozen` 후 버전·데이터 위치·hub 기동)은 여기서 다시 하지 않는다.
**아래는 모두 아직 실행해 보지 않은 항목이다** — 시험하면서 결과 칸을 채운다.

## 0. 준비

**Windows Sandbox 켜기** (Windows 11 Pro/Enterprise): `Windows 기능 켜기/끄기` → *Windows 샌드박스* 체크 → 재부팅. CPU 가상화(BIOS)가 켜져 있어야 한다.
이 PC에서 켜져 있는지는 확인하지 않았다.

**번들 만들기** (개발 PC, Node.js 필요):

```
uv run python scripts/build_release.py          # → release-out/whatever-log-<버전>-win64.zip, 마지막 줄에 sha256
```

업데이트 시험용으로 **버전이 다른 번들 하나를 더** 만든다: `VERSION`을 `1.0.0-beta.2`로 바꿔 한 번 더 빌드하고, `VERSION`은 되돌린다(커밋하지 않는다).

**zip 넣기:** 아래 `.wsb`를 `release-test.wsb`로 저장해(경로는 본인 것으로) 더블클릭한다. `release-out`이 샌드박스의 바탕화면 `release-out`으로 **읽기 전용** 공유된다.

```xml
<Configuration>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>C:\Users\user\devspace\whatever-log-pack\release-out</HostFolder>
      <SandboxFolder>C:\Users\WDAGUtilityAccount\Desktop\release-out</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <Networking>Enable</Networking>
</Configuration>
```

- 샌드박스를 **닫으면 모든 것이 사라진다.** 결과와 로그는 닫기 전에 메모하거나 캡처한다(공유 폴더는 읽기 전용이라 로그를 거기에 쓸 수 없다).
- 샌드박스의 사용자 이름은 `WDAGUtilityAccount`다. 데이터 폴더는 `C:\Users\WDAGUtilityAccount\AppData\Local\whatever.log`가 된다.
- 번들의 SHA-256이 빌드 때 출력된 값과 같은지 먼저 확인한다: `Get-FileHash <zip> -Algorithm SHA256`.

## 1. 시험 항목

각 항목의 **기대 결과**가 안 나오면 실패다. 실패하면 맨 아래 "실패했을 때 모을 것"을 모은다.

### A. 설치 전 (깨끗한 상태)

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| A1 | `uv`, `python`, `node`를 실행해 본다 | 모두 없다(= 깨끗한 환경이다) | |
| A2 | zip을 **바탕화면에 복사**해서 푼다(공유 폴더에서 바로 풀지 않는다 — 읽기 전용이라 `.venv`를 못 만든다) | `whatever-log-<버전>` 폴더, 안에 `install.cmd`·`release.json`·`apps\`·`packages\` | |
| A3 | uv가 **없는 채로** `install.cmd` 실행 | "uv가 필요해요" 안내가 나오고 멈춘다(창이 바로 닫히지 않는다), 아무것도 설치되지 않는다 | |
| A4 | 안내에 적힌 `winget install --id=astral-sh.uv -e`를 실행 | uv가 설치된다. **Sandbox에는 winget이 없을 수 있다** — 그러면 안내 문구를 고쳐야 할지 판단한다(일반 Windows 11에는 보통 있다). 없으면 PowerShell로 `irm https://astral.sh/uv/install.ps1 \| iex` | |

### B. 설치

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| B1 | 새 터미널에서 `install.cmd` 실행(uv가 PATH에 잡힌 새 창) | `[1/2]` 파이썬 환경 → `[2/2]` 설치. uv가 **Python 3.14와 의존성을 내려받는다**(시간·오류 메모) | |
| B2 | 설치 출력을 읽는다 | 기록기·동기화 에이전트 자동 시작 등록, 시작 메뉴 바로가기, 둘 다 "지금 시작했어요". `문제:` 줄이 없다. `화면: 이미 빌드되어 있어요` | |
| B3 | 종료 코드 | 마지막에 `pause`로 멈추고, 문제가 없으면 0 | |
| B4 | `uv run whatever-log status` | 기록기·에이전트 "실행 중", 자동 시작 등록됨, 화면 빌드됨, 버전 `1.0.0-beta.1`(번들 버전), 데이터 폴더 `…\AppData\Local\whatever.log` | |
| B5 | 작업 관리자에서 `pythonw.exe` | 기록기·에이전트의 supervisor와 프로그램이 떠 있다(콘솔 창은 없다) | |
| B6 | 설치 직후 데이터 폴더 | 생겼다(`recorder.db`, `goals.db` 등). 번들 폴더 **안에는** `.db`·`.log`가 없다 | |

### C. 실행과 화면

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| C1 | 시작 메뉴에서 **whatever.log** 검색 | 바로가기가 있고 **책 모양 아이콘**이다(파이썬 아이콘이 아니다) | |
| C2 | 바로가기 실행 | 창이 뜬다(WebView2 필요 — 없으면 창이 안 뜨거나 오류). 빈 화면이 아니라 사용 현황 화면이다 | |
| C3 | 작업표시줄·제목 표시줄·Alt+Tab | 앱 아이콘이다(python 기본 아이콘이 아니다). 작은 크기에서 `w`로 읽히는지 눈으로 본다 | |
| C4 | 창을 닫는다 | hub가 함께 끝난다. 기록기·에이전트는 계속 돈다(`status`) | |
| C5 | 바로가기를 다시 실행 | 구성 요소를 중복으로 띄우지 않는다(`pythonw.exe` 수가 늘지 않는다) | |
| C6 | 앱을 **몇 분 사용**(브라우저·메모장 전환) 후 화면 새로고침 | 사용 현황에 방금 쓴 프로세스가 보인다. 데이터가 `…\AppData\Local\whatever.log\recorder.db`에 쌓인다 | |
| C7 | 목표를 하나 만들고 창을 닫았다 다시 연다 | 목표가 남아 있다(`goals.db`) | |
| C8 | `…\whatever.log\logs\` | `recorder.log`, `supervisor.log`, `hub.log`, `hub-supervisor.log`, `sync.log`, `sync-supervisor.log`가 있고 오류(ERROR)가 반복되지 않는다 | |

### D. 로그인·동기화 (서버가 배포돼 있을 때만)

서버(`apps/server`)가 아직 배포되지 않았다면 건너뛴다(이 경우 로그인 버튼은 서버에 닿지 못한다는 안내가 나와야 하고, 나머지 기능은 정상이어야 한다 — 이것도 D0으로 확인한다).

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| D0 | 서버에 닿지 못하는 상태에서 로그인 시도 | 오류 안내만 나오고 기록·목표·집계는 그대로 동작한다 | |
| D1 | Google 로그인(샌드박스의 Edge) | 로그인 완료, 동기화 확인 창이 뜬다 | |
| D2 | 목표 동기화를 켠다 | 상태 칩이 "동기화됨"(기록 후 최대 한 주기 = 5분 뒤) | |

### E. 자동 시작

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| E1 | 샌드박스 안에서 **재시작**(시작 메뉴 → 다시 시작) | 다시 로그인하면 기록기·에이전트가 **저절로 떠 있다**(`status`). 재시작을 지원하지 않는 환경이면 실제 PC에서 확인한다 | |
| E2 | 재시작 뒤 데이터 | 시험 전에 쌓은 기록·목표가 그대로다(샌드박스는 재시작해도 유지된다) | |

### F. 업데이트

두 번째 번들(`1.0.0-beta.2`)을 **다른 폴더**에 푼다.

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| F1 | 새 폴더에서 `install.cmd` 실행(이전 폴더 프로그램은 **아직 떠 있는 채로**) | `다른 폴더의 설치(…)가 등록돼 있었어요 … 이전 폴더에서 whatever-log stop을 먼저 실행` 안내가 나온다. 감독 없이 떠 있는 프로그램 안내(`문제:`)가 나오면 그 내용이 이해되는지 본다 | |
| F2 | 이전 폴더에서 `uv run whatever-log stop`, 새 폴더에서 `start` | 새 폴더의 구성 요소가 뜬다. `status`의 버전이 `1.0.0-beta.2`, 자동 시작이 새 폴더를 가리킨다 | |
| F3 | 데이터 | C6·C7에서 만든 기록·목표가 **그대로 이어진다**(같은 데이터 폴더) | |
| F4 | 이전 폴더를 지운다 | 새 설치는 영향이 없다 | |

### G. 경로·환경 변형

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| G1 | **공백과 한글**이 든 폴더(`C:\Users\WDAGUtilityAccount\Desktop\테스트 폴더`)에 새로 풀어 설치 | B와 같다. 자동 시작 명령이 인자 하나로 유지되고(로그인 시 뜬다), 바로가기가 열린다 | |
| G2 | 기본 코드 페이지(cp949) cmd에서 `install.cmd` | 한글 안내가 깨지지 않는다(`chcp 65001`) | |
| G3 | 설치 중 **인터넷 끊기**(`.wsb`에서 `<Networking>Disable</Networking>`로 새 샌드박스) | `uv sync` 실패 안내("인터넷 연결을 확인…")가 나오고 멈춘다. 반쯤 설치된 등록이 없다 | |
| G4 | `WHATEVER_LOG_DATA_DIR`를 **상대 경로**로 두고 다른 폴더에서 `status` | 설치 폴더 기준 경로가 나온다 | |

### H. 제거

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| H1 | `uv run whatever-log uninstall` | 프로세스가 꺼지고(`pythonw.exe` 없음), 자동 시작 등록·바로가기가 지워진다. 종료 코드 0 | |
| H2 | 데이터 폴더 | **남아 있다**("지우지 않았어요" 안내와 일치) | |
| H3 | 다시 `install` | 데이터가 이어지고 정상 기동한다 | |

### I. 보안 경고 (사람이 받는 경험)

공유 폴더로 복사한 파일에는 "인터넷에서 받음" 표시(Mark of the Web)가 없어서 이 항목은 **실제 릴리스를 브라우저로 내려받아야** 재현된다(첫 릴리스 후).

| # | 하는 일 | 기대 결과 | 결과 |
| --- | --- | --- | --- |
| I1 | GitHub Release에서 zip을 Edge로 내려받아 풀고 `install.cmd` 실행 | SmartScreen/Defender 경고가 뜨는지 기록한다(서명이 없어 뜰 수 있다). 사용자가 "실행"으로 진행할 수 있는지, 안내가 필요한지 판단한다 | |
| I2 | Defender가 `pythonw.exe`·`.lnk`·자동 시작 등록을 차단/격리하는지 | 차단되지 않는다 | |

## 2. 실패했을 때 모을 것

닫으면 사라지므로 **닫기 전에** 모은다.

- `install.cmd`의 출력 전체(스크린샷 또는 복사)
- `uv run whatever-log status` 출력
- `C:\Users\WDAGUtilityAccount\AppData\Local\whatever.log\logs\*.log` — 로그에는 프로세스·사이트 이름이 들어갈 수 있으므로, 공유하기 전에 훑어본다(접근 로그는 식별자를 가린다)
- Run 키: `reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- 바로가기: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\whatever.log.lnk`의 대상·인자·시작 위치

## 3. Sandbox로 확인할 수 없는 것

- **GitHub Actions 릴리스 워크플로**: 태그를 푸시해야 돈다. 첫 `v1.0.0-beta.1`로 확인한다 — pre-release로 올라오는지, 설명의 SHA-256이 zip과 같은지, 태그와 `VERSION`이 다를 때 멈추는지(별도 시험 태그).
- **느린 PC**에서 창 아이콘이 붙는 시점(`shown` 이벤트라 지연과 무관해야 한다), 백신 제품별 반응, 회사 PC의 정책(프록시·실행 제한).
- **실제 재부팅**의 자동 시작 타이밍(로그인 직후 기록기가 먼저 뜨는지).
- 여러 모니터·고해상도 배율에서 아이콘 모양.

## 4. 결과 기록

시험한 날짜·번들 버전·환경을 적고, 위 표의 결과 칸에 `OK` / `FAIL(메모)` / `건너뜀(이유)`를 적는다. 실패에서 고친 것은 이 문서와 `docs/packaging.md`에 반영한다.

| 날짜 | 번들 버전 | 환경 | 요약 |
| --- | --- | --- | --- |
| | | | |
