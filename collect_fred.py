# -*- coding: utf-8 -*-
"""
collect_fred.py  —  FRED(세인트루이스 연준) 글로벌 매크로 수집기
사용법:  C:/python312/python.exe collect_fred.py
필요:    .env 에  FRED_KEY=발급받은키   (같은 폴더)
출력:    fred_daily.parquet, fred_monthly.parquet
"""
import os, sys, time, json
from datetime import datetime
import urllib.request
import pandas as pd

# ---- credentials ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

KEY = os.environ.get("FRED_KEY")
if not KEY:
    print("[중단] FRED_KEY 가 설정되지 않았습니다.  .env 에  FRED_KEY=...  를 넣으세요.")
    print("       (python-dotenv 미설치 시:  C:/python312/python.exe -m pip install python-dotenv)")
    sys.exit(1)
print(f"[인증] FRED_KEY = {KEY[:4]}***  (감지됨)")

START = "1995-01-01"   # 매크로는 1995년부터 (밸류는 KRX 한계로 2005~)

# 지표: 표시이름 -> FRED series_id
SERIES = {
    "VIX":        "VIXCLS",       # 변동성지수(공포지수)
    "US10Y":      "DGS10",        # 미국 국채 10년
    "US2Y":       "DGS2",         # 미국 국채 2년
    "T10Y2Y":     "T10Y2Y",       # 장단기금리차(10Y-2Y), 침체신호
    "WTI":        "DCOILWTICO",   # WTI 유가
    "USD_BROAD":  "DTWEXBGS",     # 달러 광범위 지수 (2006~)
    "HY_OAS":     "BAMLH0A0HYM2", # 미국 하이일드 신용스프레드(OAS)
    "BAA10Y":     "BAA10Y",       # Baa회사채-국채10년 스프레드 (1990~). HY_OAS는 ICE 라이선스로 최근 3년만 제공돼 장기분석 불가
    "AAA10Y":     "AAA10Y",       # Aaa회사채-국채10년 스프레드 (1990~)
    "NASDAQ":     "NASDAQCOM",    # 나스닥 종합 (1990~). SP500/DJIA는 FRED가 최근 10년만 제공
    "KRW_USD":    "DEXKOUS",      # 원/달러 (FRED판, ECOS 교차검증용)
}

def fetch(series_id):
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={KEY}&file_type=json"
           f"&observation_start={START}")
    last = None
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
            obs = d.get("observations")
            if obs is None:
                return None, d.get("error_message", "no observations")
            recs = [(o["date"], o["value"]) for o in obs if o["value"] not in (".", "")]
            if not recs:
                return None, "empty"
            s = pd.Series(
                {pd.Timestamp(dt): float(v) for dt, v in recs}
            ).sort_index()
            return s, None
        except Exception as e:
            last = str(e)
            time.sleep(1.5 * (i + 1))
    return None, last

print(f"[수집] {START} ~ 현재  ({len(SERIES)}개 지표)\n")
cols = {}
for name, sid in SERIES.items():
    s, err = fetch(sid)
    if s is None:
        print(f"  x {name:11s} ({sid:14s})  실패: {err}")
    else:
        cols[name] = s
        print(f"  · {name:11s} ({sid:14s})  {s.index[0].date()} ~ {s.index[-1].date()}  ({len(s)} obs)")
    time.sleep(0.4)

if not cols:
    print("\n[중단] 수집된 시리즈가 없습니다. 키/네트워크 확인 필요.")
    sys.exit(1)

daily = pd.DataFrame(cols).sort_index()
daily.index.name = "date"

# 월간: 각 시리즈 월말 마지막값
monthly = daily.resample("ME").last()

daily.to_parquet("fred_daily.parquet")
monthly.to_parquet("fred_monthly.parquet")

print("\n" + "=" * 56)
print(f"일별 : {daily.index[0].date()} ~ {daily.index[-1].date()}  ({len(daily)} rows)")
print(f"월간 : {monthly.index[0].date()} ~ {monthly.index[-1].date()}  ({len(monthly)} rows)")
print("컬럼별 유효 데이터 시작:")
for c in monthly.columns:
    s = monthly[c].dropna()
    print(f"   {c:11s}: {s.index[0].date()}  (n={len(s)})")
print("=" * 56)
print("저장 완료 → fred_daily.parquet, fred_monthly.parquet")
