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

REM 1) collect data (KRX/ECOS/FRED/KOFIA/VKOSPI/FLOW)
C:\python312\python.exe update_all.py >> "%LOG%" 2>&1

REM 2) rebuild the local dashboard EXPLICITLY (~4s)
REM    Do not leave this to notify_regime.py. That script happens to regenerate
REM    dashboard.html as a side effect of importing build_dashboard; if that import
REM    is ever moved into a function or wrapped in try/except, the screen goes stale
REM    silently with no error in the log. An explicit line removes that trap.
REM    (the cloud rebuilds docs/index.html separately - see .github/workflows/update.yml)
C:\python312\python.exe build_dashboard.py >> "%LOG%" 2>&1


REM 3) commit BEFORE pull, then pull, then push.
REM    Pulling first breaks when a tracked file was changed locally by the build
REM    (proj_history.json, which build_dashboard.py appends to every run).
REM    git aborts the merge and can leave the working tree half-reverted,
REM    silently rolling parquet files back to the remote version.
REM    That is exactly what happened on 2026-09-01: collection wrote data through
REM    09-01, the pull aborted, parquet reverted to 08-28, and the
REM    "No data change" branch skipped the push. Commit first removes the conflict.
git add *.parquet *.csv proj_history.json >> "%LOG%" 2>&1
git diff --staged --quiet
if errorlevel 1 (
  git commit -m "auto data update" >> "%LOG%" 2>&1
  echo Committed local data. >> "%LOG%"
) else (
  echo Nothing new to commit. >> "%LOG%"
)
git pull --no-edit >> "%LOG%" 2>&1
git push >> "%LOG%" 2>&1

REM 4) notify by telegram only when the regime band changed
C:\python312\python.exe notify_regime.py >> "%LOG%" 2>&1

echo Run finished: %date% %time% >> "%LOG%"
