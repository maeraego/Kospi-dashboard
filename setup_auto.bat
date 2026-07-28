@echo off
REM ============================================
REM  setup_auto.bat - register auto-run (run once)
REM  Registers two scheduled tasks:
REM   (1) at every logon (PC power on)
REM   (2) daily at 18:30 (after market close + KRX aggregation)
REM  No admin rights needed. Just double-click.
REM ============================================
cd /d "%~dp0"

set TASK1=KospiUpdate_Logon
set TASK2=KospiUpdate_Daily
set BAT=%~dp0auto_update.bat

echo ==============================================
echo   KOSPI Dashboard - Auto Update Setup
echo ==============================================
echo.
echo   Target: %BAT%
echo.
echo   (1) Run at logon (when you turn on the PC)
echo   (2) Run daily at 18:30
echo.
echo   * Internet connection is required.
echo   * If PC was off at 18:30, (1) runs at next logon.
echo.
pause

REM (1) run at logon, 1 minute after
schtasks /Create /TN "%TASK1%" /TR "\"%BAT%\"" /SC ONLOGON /DELAY 0001:00 /F

REM (2) run daily at 18:30
schtasks /Create /TN "%TASK2%" /TR "\"%BAT%\"" /SC DAILY /ST 18:30 /F

if errorlevel 1 (
  echo.
  echo   [!] Failed. Try: right-click this file - Run as administrator
) else (
  echo.
  echo   Done! It will update automatically from now on.
  echo.
  echo   Run once now:   schtasks /Run /TN "%TASK2%"
  echo   Check status:   schtasks /Query /TN "%TASK2%"
  echo   Remove:         schtasks /Delete /TN "%TASK2%" /F
  echo                   schtasks /Delete /TN "%TASK1%" /F
  echo   Run log:        auto_update_log.txt
)
echo.
pause
