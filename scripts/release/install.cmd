@echo off
rem whatever.log 설치: 자동 시작·바로가기를 등록하고 시작한다. 파이썬은 이 폴더에 들어 있어서 따로 설치할 것이 없다.
rem 이 폴더를 그대로 두고 쓰는 방식이라, 다른 곳으로 옮겼다면 이 파일을 다시 실행하세요.
chcp 65001 >nul
cd /d "%~dp0"

if not exist "runtime\whatever-log-cli.exe" (
  echo 이 폴더에 runtime\whatever-log-cli.exe가 없어요. zip을 끝까지 푼 폴더에서 실행했는지 확인해 주세요.
  pause
  exit /b 1
)

"runtime\whatever-log-cli.exe" -m launcher install %*
set RESULT=%ERRORLEVEL%
pause
exit /b %RESULT%
