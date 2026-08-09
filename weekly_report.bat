@echo off
REM ============================================
REM  weekly_report.bat - 주간 리포트 (작업 스케줄러가 호출)
REM  DRAM(ECOS+TrendForce) / OpenRouter 수집 -> 차트 -> 텔레그램 발송
REM  각 단계는 실패해도 다음 단계로 넘어간다(스크립트가 항상 exit 0).
REM ============================================
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PY=C:\python312\python.exe

set LOG=weekly_report_log.txt
echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo Run started: %date% %time% >> "%LOG%"

REM 1) DRAM - ECOS 월간지수 + TrendForce 현물/계약 누적
%PY% collect_dram.py >> "%LOG%" 2>&1
%PY% report_dram.py  >> "%LOG%" 2>&1

REM 2) 관세청 - 실제 달러금액/중량 (CUSTOMS_KEY 없으면 조용히 건너뜀)
%PY% collect_customs.py >> "%LOG%" 2>&1

REM 3) OpenRouter - 회사별 토큰 스냅샷 누적
%PY% collect_openrouter.py >> "%LOG%" 2>&1
%PY% report_openrouter.py  >> "%LOG%" 2>&1

echo Run finished: %date% %time% >> "%LOG%"
