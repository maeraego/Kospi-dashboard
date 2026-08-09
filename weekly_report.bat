@echo off
REM ============================================
REM  weekly_report.bat - weekly report (called by Task Scheduler)
REM  DRAM (ECOS + TrendForce) / Customs / OpenRouter
REM    -> collect -> chart -> send to Telegram
REM  Each python script always exits 0, so one failure
REM  does not stop the following steps.
REM
REM  NOTE: keep this file ASCII only.
REM  cmd.exe reads .bat in the system codepage (CP949 here),
REM  so UTF-8 Korean comments corrupt the following lines.
REM ============================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY=C:\python312\python.exe

set LOG=weekly_report_log.txt
echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo Run started: %date% %time% >> "%LOG%"

REM 1) DRAM - ECOS monthly index + TrendForce spot/contract accumulation
%PY% collect_dram.py >> "%LOG%" 2>&1
%PY% report_dram.py  >> "%LOG%" 2>&1

REM 2) Customs - real USD amount / weight (skipped if CUSTOMS_KEY missing)
%PY% collect_customs.py >> "%LOG%" 2>&1

REM 3) OpenRouter - token usage snapshot by company
%PY% collect_openrouter.py >> "%LOG%" 2>&1
%PY% report_openrouter.py  >> "%LOG%" 2>&1

echo Run finished: %date% %time% >> "%LOG%"
