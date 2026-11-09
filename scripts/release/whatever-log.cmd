@echo off
rem 관리 명령: whatever-log.cmd status | start | stop | uninstall | install | --version
"%~dp0runtime\whatever-log-cli.exe" -m launcher %*
exit /b %ERRORLEVEL%
