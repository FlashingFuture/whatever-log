# 메모리 사용과 작업 관리자의 표시

작업 관리자에서 whatever.log가 차지하는 것은 세 덩어리다: **창 프로세스(파이썬 + .NET)**, **WebView2(화면을 그리는 Chromium)**, **백그라운드 프로세스(기록기·동기화 에이전트·hub·supervisor)**.
아래 숫자는 모두 이 PC에서 같은 방식으로 잰 값이고(작업 집합·전용 메모리 MB, 시작 25~50초 뒤), 비교는 "고친 것"과 "고치기 전"을 같은 조건에서 돌려 얻었다.

## 한 일

| 대상 | 방법 | 전 → 후 |
| --- | --- | --- |
| WebView2 전체(프로세스 6개) | `--disable-gpu`로 GPU 프로세스를 따로 띄우지 않는다(`desktop.configure_webview2`) | 전용 **107.6 → 62.8MB**(−42%), CPU 사용은 같다(20초에 0.35초 vs 0.36초) |
| 창 프로세스 | hub 포트 숫자 하나를 얻으려고 `hub.__main__`을 통째로 불러오던 것을 `common.ports`로 | 전용 49.2 → 46.5MB |
| 기록기 | 쉬는 시간이 긴 프로세스는 안 쓰는 물리 메모리를 운영체제에 돌려준다(`common.memory.keep_trimmed`) | 작업 집합 **34.5 → 9.4MB**(작업 관리자 "메모리") |
| hub | 같음 | 38.6 → **5.4MB** |
| 동기화 에이전트 | 같음 | 49.9 → **6.9MB** |
| supervisor(둘) | 같음 | 약 1MB |

### 알아둘 점
- **`--disable-gpu`**: Microsoft는 문제 진단 외에는 권하지 않는다(소프트웨어 렌더링이라 애니메이션이 많은 화면에서는 CPU를 더 쓴다). 이 화면은 글자·막대 몇 개라 CPU가 늘지 않았다(위 표). 화면에 애니메이션·차트를 많이 넣게 되면 다시 잰다.
  사용자가 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` 환경변수를 이미 정해 두었으면 그 값을 따른다(덮어쓰지 않는다).
- **작업 집합 줄이기(`EmptyWorkingSet`)는 "약속한 메모리(commit)"를 줄이지 않는다.** 지금 안 쓰는 물리 메모리 페이지를 운영체제에 돌려주는 것이라, 작업 관리자의 숫자는 크게 내려가고 메모리가 모자랄 때는
  실제로 도움이 되지만, 프로세스가 필요하면 다시 읽어 들인다. 그래서 **쉬는 시간이 긴 백그라운드 프로세스에만** 쓰고(시작 30초 뒤 한 번, 그 뒤 5분마다), 사용자가 보고 있는 창 프로세스에는 쓰지 않는다 — 다시 읽느라 버벅일 수 있다.
  시작 직후에 줄이면 모듈을 불러오는 동안 곧바로 다시 차오르므로 첫 정리는 30초 뒤다.
- 창 프로세스(파이썬 + .NET) 약 46MB는 pywebview가 .NET(WinForms)과 WebView2 연결을 메모리에 올리기 때문이라 더 줄이기 어렵다.

## 하지 못한 것 (이유와 선택지)

### 1. 프로세스 이름이 `pythonw`로 보이는 것
작업 관리자(프로세스·시작 프로그램 탭)가 보여 주는 이름은 **실행 파일의 이름**이다. 우리 프로세스는 파이썬 인터프리터(`pythonw.exe`·`python.exe`)로 돌기 때문에 `pythonw`로 보인다 — 이 이름은 코드로 바꿀 수 없다.
시작 프로그램 탭도 같다: 등록한 값 이름(`WhateverLogRecorder`)이 아니라 실행 파일 이름(`pythonw`)이 나온다(이 PC에서 확인).
WebView2 프로세스는 이름이 `Microsoft Edge WebView2`로 고정이고, 최신 Windows 11의 작업 관리자는 그것을 **그것을 띄운 앱(호스트)** 아래에 묶어 보여 준다 — 호스트가 `pythonw`면 그 밑에 묶인다.

해결하려면 **실행 파일 이름이 `whatever-log.exe`인 인터프리터**를 써야 한다. PR #38(릴리스 번들에 이름만 바꾼 파이썬을 담는다)이 그 방식이었고, 창·기록기·hub가 `whatever-log.exe`로 뜨고 recorder의 사용 현황에도 그 이름으로 기록되는 것까지
확인했다. **릴리스 번들에는 이 방식이 들어 있다**(`docs/packaging.md`). 개발용 저장소(`uv run`)에서는 계속 `python.exe`·`pythonw.exe`로 보인다. 개발하던 PC에서 번들로 갈아타려면 `whatever-log.cmd import-data`로 기록을 복사한다.

### 2. 시작 프로그램의 "시작 영향: 측정되지 않음"을 "낮음"으로 만드는 것
이 값은 **Windows가 부팅 때의 CPU·디스크 사용을 직접 재서** 정한다(앱이 정하거나 레지스트리로 지정할 수 없다). 등록한 뒤 아직 부팅 때 실행된 기록이 없거나, 측정 대상이 되지 못한 항목은 "측정되지 않음"이다.
재부팅을 몇 번 거치고 시작 후 Windows가 백그라운드 작업을 마치면 채워지는 경우가 많다. 그래도 계속 비어 있으면 이 앱이 할 수 있는 일은 없다.
(참고: [winhelponline](https://www.winhelponline.com/blog/task-manager-startup-impact-calculated-bootckcl/), [The Windows Club](https://www.thewindowsclub.com/startup-impact-not-measured-in-task-manager))
