@echo off
REM 매일 실행 배치 (Windows 작업 스케줄러가 호출)
cd /d C:\Dev\pesticide
set PYTHONIOENCODING=utf-8
if not exist out mkdir out
".venv\Scripts\python.exe" -m src.pipeline >> out\cron.log 2>&1
