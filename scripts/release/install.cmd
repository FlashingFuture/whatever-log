@echo off
rem whatever.log 설치: 파이썬 환경을 만들고(uv), 자동 시작·바로가기를 등록하고, 시작한다.
rem 이 폴더를 그대로 두고 쓰는 방식이라, 다른 곳으로 옮겼다면 이 파일을 다시 실행하세요.
chcp 65001 >nul
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv가 필요해요. 아래 명령으로 설치한 뒤 이 파일을 다시 실행해 주세요:
  echo     winget install --id=astral-sh.uv -e
  echo ^(자세한 안내: https://docs.astral.sh/uv/getting-started/installation/^)
  pause
  exit /b 1
)

echo [1/2] 파이썬 환경을 준비합니다... ^(처음에는 몇 분 걸릴 수 있어요^)
uv sync --frozen --no-dev --all-packages
if errorlevel 1 (
  echo 파이썬 환경을 만들지 못했어요. 인터넷 연결을 확인하고 다시 실행해 주세요.
  pause
  exit /b 1
)

echo [2/2] 설치합니다...
uv run --frozen --no-dev whatever-log install %*
set RESULT=%ERRORLEVEL%
pause
exit /b %RESULT%
