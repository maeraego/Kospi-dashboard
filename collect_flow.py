# -*- coding: utf-8 -*-
"""
collect_flow.py  —  투자자별 순매수(수급) 수집기  [pykrx]

코스피/코스닥의 투자자 주체별(외국인·기관 세분·개인) 순매수 대금을 받아
일별/월별 parquet으로 저장한다. 다른 collect_*.py 와 동일한 폴더에 두고 실행.

사용법:  C:/python312/python.exe collect_flow.py
필요:    pip install pykrx
출력:    flow_daily.parquet, flow_monthly.parquet

수집 항목(순매수 '대금', 억원 단위로 저장):
  외국인(외국인합계), 기관합계, 개인, 그리고 기관 세분(금융투자·투신·연기금·보험·사모 등)
  + 파생: 20일 이동합계(누적 흐름), 시가총액 대비 비율(정규화)

주의(분석 관점):
  순매수와 지수는 '같은 날' 함께 움직이므로(동시성), 단순 상관은 예측력이 아니다.
  선행성은 build_dashboard 쪽에서 '오늘 순매수 → 미래 수익' IC로 별도 검증한다.
"""
import os
import sys
from datetime import datetime

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import pandas as pd

# ── .env 로드는 반드시 pykrx import '앞'에 와야 한다 ──
#   pykrx는 import 시점에 KRX_ID/KRX_PW로 로그인을 시도한다.
#   이게 빠져 있어 2026-08 내내 자동수집이 "KRX 로그인 실패"로 끝나고 있었다
#   (collect_krx.py에는 처음부터 있었는데 이 파일만 누락).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from pykrx import stock
except Exception:
    print("[중단] pykrx 가 설치되어 있지 않습니다.")
    print("       C:/python312/python.exe -m pip install pykrx")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
START = "20050101"
END = datetime.today().strftime("%Y%m%d")

# 저장할 주체(원본 pykrx 컬럼명 → 저장명). 시장별로 접두어를 붙인다.
KEEP = {
    "외국인합계": "외국인",
    "기관합계": "기관",
    "개인": "개인",
    "금융투자": "금융투자",
    "투신": "투신",
    "연기금": "연기금",
    "보험": "보험",
    "사모": "사모",
}
MARKETS = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}

print("=" * 58)
print(f"  투자자별 순매수 수집 (pykrx)  {START} ~ {END}")
print("=" * 58)


def fetch_market(mkt):
    """시장 전체의 투자자별 순매수 '대금' 일별 시계열."""
    try:
        # 순매수 거래대금 (원). 시장 단위 조회.
        df = stock.get_market_trading_value_by_date(START, END, mkt, on="순매수")
    except TypeError:
        df = stock.get_market_trading_value_by_date(START, END, mkt)
    except Exception as e:
        print(f"  [실패] {mkt}: {e}")
        return None
    if df is None or df.empty:
        print(f"  [경고] {mkt}: 빈 데이터")
        return None
    df.index = pd.to_datetime(df.index)
    # 외국인합계가 없고 '외국인'만 있는 버전 대응
    if "외국인합계" not in df.columns and "외국인" in df.columns:
        df = df.rename(columns={"외국인": "외국인합계"})
    cols = {}
    for raw, save in KEEP.items():
        if raw in df.columns:
            cols[f"{mkt}_순매수_{save}"] = df[raw] / 1e8   # 원 → 억원
    out = pd.DataFrame(cols)
    print(f"  [{mkt}] {len(out)}일 · 주체 {len(out.columns)}개: "
          f"{', '.join(c.split('_')[-1] for c in out.columns)}")
    return out


parts = []
for mkt in MARKETS:
    r = fetch_market(mkt)
    if r is not None:
        parts.append(r)

if not parts:
    print("\n[중단] 수집된 데이터가 없습니다. pykrx 버전/네트워크를 확인하세요.")
    sys.exit(1)

daily = pd.concat(parts, axis=1).sort_index()

# ── 파생지표: 20일 이동합계(누적 흐름), 시총 대비 비율 ──
extra = {}
try:
    krx_d = pd.read_parquet(os.path.join(HERE, "krx_daily.parquet"))
except Exception:
    krx_d = None

for mkt in MARKETS:
    for save in ("외국인", "기관", "개인", "연기금"):
        col = f"{mkt}_순매수_{save}"
        if col in daily.columns:
            extra[f"{mkt}_순매수20_{save}"] = daily[col].rolling(20).sum()
            if krx_d is not None and f"{mkt}_시총" in krx_d.columns:
                mcap = krx_d[f"{mkt}_시총"].reindex(daily.index).ffill() / 1e8  # 억원
                # 20일 누적 순매수를 시총으로 정규화(%) — 규모효과 제거
                extra[f"{mkt}_순매수20비율_{save}"] = (
                    daily[col].rolling(20).sum() / mcap * 100)

daily = pd.concat([daily, pd.DataFrame(extra, index=daily.index)], axis=1)

# 월별: 순매수는 '합계'가 맞고, 파생 이동합계·비율은 월말값 사용
monthly_sum = daily[[c for c in daily.columns if "_순매수_" in c]].resample("ME").sum()
monthly_last = daily[[c for c in daily.columns
                      if "_순매수20" in c]].resample("ME").last()
monthly = pd.concat([monthly_sum, monthly_last], axis=1)

daily.to_parquet(os.path.join(HERE, "flow_daily.parquet"))
monthly.to_parquet(os.path.join(HERE, "flow_monthly.parquet"))

print("\n" + "-" * 58)
print(f"저장 완료:")
print(f"  flow_daily.parquet    {daily.index[0].date()} ~ {daily.index[-1].date()}  "
      f"({len(daily)}일, {daily.shape[1]}열)")
print(f"  flow_monthly.parquet  {monthly.index[0].date()} ~ {monthly.index[-1].date()}  "
      f"({len(monthly)}개월, {monthly.shape[1]}열)")
print("-" * 58)
print("최근 3개월 순매수(억원) 샘플:")
_show = [c for c in monthly.columns if "_순매수_" in c
         and any(k in c for k in ("외국인", "기관", "개인"))]
print(monthly[_show].tail(3).round(0).to_string())
print("\n다음: build_dashboard.py 를 다시 실행하면 수급 IC 검증 결과가 반영됩니다.")
