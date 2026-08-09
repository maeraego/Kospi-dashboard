@echo off
REM ============================================
REM  auto_update.bat - unattended auto run
REM  (called by Task Scheduler; no human needed)
REM  collect data -> push parquet to GitHub -> cloud rebuilds dashboard
REM ============================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

set LOG=auto_update_log.txt
echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo Run started: %date% %time% >> "%LOG%"

REM 1) collect data (KRX/ECOS/FRED/FLOW)
C:\python312\python.exe update_all.py >> "%LOG%" 2>&1

REM 2) pull remote first (avoid push rejection), then push if data changed
git pull --no-edit >> "%LOG%" 2>&1
git add *.parquet *.csv >> "%LOG%" 2>&1
git diff --staged --quiet
if errorlevel 1 (
  git commit -m "auto data update" >> "%LOG%" 2>&1
  git push >> "%LOG%" 2>&1
  echo Pushed new data. >> "%LOG%"
) else (
  echo No data change - skip push. >> "%LOG%"
)

REM 3) notify by telegram only when the regime band changed
C:\python312\python.exe notify_regime.py >> "%LOG%" 2>&1

echo Run finished: %date% %time% >> "%LOG%"
