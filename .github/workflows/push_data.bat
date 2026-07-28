@echo off
REM ============================================
REM  push_data.bat  -  \xEC\xA7\x91 PC\xEC\x97\x90\xEC\x84\x9C \xEB\x8D\xB0\xEC\x9D\xB4\xED\x84\xB0 \xEC\x88\x98\xEC\xA7\x91 \xED\x9B\x84 GitHub\xEC\x97\x90 \xEC\x98\xAC\xEB\xA6\xBC
REM  \xED\x81\xB4\xEB\x9D\xBC\xEC\x9A\xB0\xEB\x93\x9C\xEA\xB0\x80 \xEC\x9D\xB4\xEA\xB1\xB8 \xEA\xB0\x90\xEC\xA7\x80\xED\x95\xB4 \xEB\x8C\x80\xEC\x8B\x9C\xEB\xB3\xB4\xEB\x93\x9C\xEB\xA5\xBC \xEC\x9E\xAC\xEC\x83\x9D\xEC\x84\xB1\xED\x95\x9C\xEB\x8B\xA4
REM ============================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ==========================================
echo   Collecting data on local PC...
echo ==========================================
C:\python312\python.exe update_all.py

echo.
echo   Pushing parquet files to GitHub...
git add *.parquet *.csv
git commit -m "data update"
git push

echo.
echo   Done. Cloud will rebuild the dashboard in ~1 min.
echo   Check: https://maeraego.github.io/Kospi-dashboard/
echo.
pause
