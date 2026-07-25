# -*- coding: utf-8 -*-
"""
collect_krx.py  —  KOSPI/KOSDAQ 지수 데이터 수집기 (1995년부터)

pykrx로 지수 종가·시가총액·PER·PBR을 받아 일별/월별 parquet으로 저장한다.

  · 지수 종가/시총: 코스피 1995년~, 코스닥 1996년 7월 개장 이후~
  · PER/PBR: KRX가 제공하는 시점부터 (지수 펀더멘털은 종가보다 늦게 시작)
  · 받을 수 있는 만큼 받고, 없는 구간은 비워둔 채 저장한다.

사용법:  C:/python312/python.exe collect_krx.py
        (특정 연도부터)  ... collect_krx.py --from 1995
필요:    pip install pykrx   /  .env 에 KRX_ID, KRX_PW
출력:    krx_daily.parquet, krx_monthly.parquet
"""
import os
import sys
import time
from datetime import datetime

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from pykrx import stock
except Exception:
    print("[중단] pykrx 가 없습니다.  C:/python312/python.exe -m pip install pykrx")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))

START_YEAR = 1995
if '--from' in sys.argv:
    try:
        START_YEAR = int(sys.argv[sys.argv.index('--from') + 1])
    except Exception:
        pass
END = datetime.today()

TICKERS = {'KOSPI': '1001', 'KOSDAQ': '2001'}
# 지수 개장 시점 — 그 이전은 요청해도 빈 값
INCEPTION = {'KOSPI': 1980, 'KOSDAQ': 1996}

print("=" * 60)
print(f"  KRX 지수 수집  {START_YEAR}년 ~ {END.year}년")
print("=" * 60)
if os.environ.get('KRX_ID'):
    print(f"[인증] KRX_ID 감지됨 ({os.environ['KRX_ID'][:3]}***)")
else:
    print("[경고] KRX_ID 없음 — 2025년 말 이후 로그인 필요 구간에서 실패할 수 있습니다.")


def year_chunks(y0, y1):
    for y in range(y0, y1 + 1):
        yield f"{y}0101", f"{y}1231"


def fetch(fn, s, e, tk, label):
    """연도별 조회. 실패해도 전체를 멈추지 않는다."""
    for attempt in range(3):
        try:
            return fn(s, e, tk)
        except Exception as ex:
            if attempt == 2:
                print(f"      ! {label} {s[:4]} 실패: {str(ex)[:60]}")
                return None
            time.sleep(1.2)
    return None


daily_parts = []
for name, tk in TICKERS.items():
    y0 = max(START_YEAR, INCEPTION[name])
    print(f"\n▶ {name} (티커 {tk})  {y0}년부터")
    ohlcv, fund = [], []
    for s, e in year_chunks(y0, END.year):
        d1 = fetch(stock.get_index_ohlcv, s, e, tk, f"{name} 시세")
        if d1 is not None and not d1.empty:
            ohlcv.append(d1)
        d2 = fetch(stock.get_index_fundamental, s, e, tk, f"{name} 펀더멘털")
        if d2 is not None and not d2.empty:
            fund.append(d2)
        time.sleep(0.15)

    if not ohlcv:
        print(f"   [실패] {name} 시세를 전혀 받지 못했습니다.")
        continue

    O = pd.concat(ohlcv).sort_index()
    O = O[~O.index.duplicated(keep='last')]
    cols = {}
    if '종가' in O.columns:
        cols[f'{name}_종가'] = O['종가']
    # 시가총액 컬럼명이 버전에 따라 다름
    for cand in ('상장시가총액', '시가총액'):
        if cand in O.columns:
            cols[f'{name}_시총'] = O[cand] / 1e12      # 원 → 조원
            break
    part = pd.DataFrame(cols)

    if fund:
        F = pd.concat(fund).sort_index()
        F = F[~F.index.duplicated(keep='last')]
        for c in ('PER', 'PBR'):
            if c in F.columns:
                part[f'{name}_{c}'] = F[c]
        # 선행PER — KRX가 제공하면 사용. (현재 대부분의 pykrx 버전에서는 컬럼이 없거나 0)
        for c in ('선행PER', 'FwdPER', '예상PER'):
            if c in F.columns:
                v = pd.to_numeric(F[c], errors='coerce')
                if (v > 0).sum() > 0:
                    part[f'{name}_선행PER'] = v.where(v > 0)
                    print(f"   [발견] {name} 선행PER 사용 가능 "
                          f"({int((v > 0).sum())}일, 최근 {v[v > 0].iloc[-1]:.2f})")
                else:
                    print(f"   [참고] {name} 선행PER 컬럼은 있으나 값이 전부 0 — 건너뜀")
                break
        print(f"   시세 {len(O)}일 ({O.index[0].date()}~{O.index[-1].date()})"
              f" · 펀더멘털 {len(F)}일 ({F.index[0].date()}~)")
    else:
        print(f"   시세 {len(O)}일 ({O.index[0].date()}~{O.index[-1].date()}) · 펀더멘털 없음")

    daily_parts.append(part)

if not daily_parts:
    print("\n[중단] 수집된 데이터가 없습니다.")
    sys.exit(1)

daily = pd.concat(daily_parts, axis=1).sort_index()
daily.index = pd.to_datetime(daily.index)
daily.index.name = '날짜'

# 0은 결측 표기이므로 제거 (PER=0 같은 값이 z-score를 오염시킴)
import numpy as np
daily = daily.replace(0, np.nan).replace([np.inf, -np.inf], np.nan)

# 파생 ROE = PBR/PER*100  (참고용. 모델은 PBR·PER을 직접 쓰므로 신호로는 미사용)
for name in TICKERS:
    if f'{name}_PBR' in daily and f'{name}_PER' in daily:
        daily[f'{name}_ROE'] = daily[f'{name}_PBR'] / daily[f'{name}_PER'] * 100

monthly = daily.resample('ME').last()

daily.to_parquet(os.path.join(HERE, 'krx_daily.parquet'))
monthly.to_parquet(os.path.join(HERE, 'krx_monthly.parquet'))

# KRX가 선행PER을 실제로 줬다면 fwd_per_monthly.parquet 에 합친다(기존 수동/디지타이즈 값보다 우선)
_FP = 'KOSPI_선행PER'
if _FP in monthly.columns and monthly[_FP].notna().sum() > 0:
    fp = monthly[_FP].dropna().rename('예상PER')
    out = os.path.join(HERE, 'fwd_per_monthly.parquet')
    try:
        old = pd.read_parquet(out)['예상PER']
        merged = fp.combine_first(old).sort_index()
    except Exception:
        merged = fp.sort_index()
    merged.to_frame().to_parquet(out)
    print(f"\n[선행PER] KRX 실측값 {len(fp)}개월을 fwd_per_monthly.parquet 에 반영")
    print(f"          {fp.index[0].date()} ~ {fp.index[-1].date()}")

print("\n" + "-" * 60)
print("저장 완료")
print(f"  krx_daily.parquet    {daily.index[0].date()} ~ {daily.index[-1].date()}  ({len(daily)}일)")
print(f"  krx_monthly.parquet  {monthly.index[0].date()} ~ {monthly.index[-1].date()}  ({len(monthly)}개월)")
print("\n계열별 시작 시점:")
for c in monthly.columns:
    s = monthly[c].dropna()
    if len(s):
        print(f"  {c:16s} {s.index[0].date()} ~  (n={len(s)})")
print("\n다음:  C:/python312/python.exe build_dashboard.py")
