@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ==========================================
echo   KOSPI / KOSDAQ Regime Dashboard
echo ==========================================
echo.
echo  Rebuilding dashboard from local data...
echo  (so the page always matches your parquet files)
echo.
C:\python312\python.exe build_dashboard.py
if errorlevel 1 (
  echo.
  echo  [!] Rebuild failed - opening the existing page instead.
  echo      Check the error above.
  echo.
)

echo.
echo  Starting local server...
echo  The browser will open automatically.
echo.
echo  NOTE: This rebuild uses data already on your PC.
echo        To fetch TODAY^&s market data, click the
echo        [Data Update] button on the page.
echo.
echo  Press Ctrl+C in this window to stop.
echo ==========================================
echo.
C:\python312\python.exe serve_dashboard.py
pause
