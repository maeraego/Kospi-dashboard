# -*- coding: utf-8 -*-
"""
collect_fwd_per.py  —  선행PER 자동 수집 시도 + 진단

pykrx의 get_index_fundamental()는 '선행PER' 컬럼을 반환하지만, KRX가 값을
채워주지 않고 0으로 내려보내는 경우가 있다. 이 스크립트는:

  1) 여러 날짜/지수로 선행PER을 실제로 조회해 '진짜 값이 오는지' 진단하고
  2) 유효하면 fwd_per_monthly.parquet 으로 자동 저장한다.
  3) 값이 0뿐이면, 대신 쓸 수 있는 방법(EPS 모드)을 안내한다.

사용법:  C:/python312/python.exe collect_fwd_per.py
        (진단만)  C:/python312/python.exe collect_fwd_per.py --check
"""
import os
import sys
from datetime import datetime, timedelta

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
CHECK_ONLY = '--check' in sys.argv
KOSPI_TICKER = "1001"

if os.environ.get("KRX_ID"):
    print(f"[인증] KRX_ID 감지됨 ({os.environ['KRX_ID'][:3]}***) - 로그인 데이터 접근 시도")
else:
    print("[인증] KRX_ID 없음 - 공개 데이터만 조회")

print("=" * 60)
print("  선행PER 자동수집 진단")
print("=" * 60)

# ── 1) 최근 며칠을 찍어서 선행PER이 실제 값인지 확인 ──
today = datetime.today()
probe_start = (today - timedelta(days=20)).strftime("%Y%m%d")
probe_end = today.strftime("%Y%m%d")

print(f"\n[1] 최근 조회: {probe_start} ~ {probe_end}  (코스피)")
try:
    probe = stock.get_index_fundamental(probe_start, probe_end, KOSPI_TICKER)
except Exception as e:
    print(f"  [실패] {e}")
    probe = None

fwd_ok = False
if probe is not None and not probe.empty:
    print(f"  컬럼: {list(probe.columns)}")
    if "선행PER" in probe.columns:
        s = pd.to_numeric(probe["선행PER"], errors="coerce")
        nz = s[s > 0]
        print(f"  선행PER 표본 {len(s)}개 중 0이 아닌 값: {len(nz)}개")
        if len(nz):
            print(f"  최근 값: {nz.iloc[-1]:.2f}  (범위 {nz.min():.2f}~{nz.max():.2f})")
            fwd_ok = True
        else:
            print("  → 전부 0. KRX가 이 필드를 채우지 않고 있습니다.")
    else:
        print("  → '선행PER' 컬럼 자체가 없습니다 (pykrx 버전 확인 필요)")
else:
    print("  → 데이터를 받지 못했습니다 (휴장/네트워크 확인)")

# ── 2) 과거 구간도 확인 (과거엔 채워졌을 수 있음) ──
print(f"\n[2] 과거 표본 점검")
for yr in (2015, 2020, 2024):
    try:
        p = stock.get_index_fundamental(f"{yr}0601", f"{yr}0615", KOSPI_TICKER)
        if p is not None and not p.empty and "선행PER" in p.columns:
            s = pd.to_numeric(p["선행PER"], errors="coerce")
            nz = s[s > 0]
            mark = f"{nz.iloc[-1]:.2f}" if len(nz) else "0 (없음)"
            print(f"  {yr}: {mark}")
        else:
            print(f"  {yr}: 조회 실패")
    except Exception as e:
        print(f"  {yr}: 오류 {e}")

# ── 3) 결과에 따라 저장 or 안내 ──
print("\n" + "=" * 60)
if not fwd_ok:
    print("결론: pykrx/KRX 경로로는 선행PER을 받을 수 없습니다.")
    print()
    print("대안 — 'EPS 모드'를 쓰세요. 매일 입력할 필요가 없어집니다:")
    print("   선행PER = 코스피지수 / 12개월 예상EPS")
    print("   지수는 이미 매일 자동 수집되므로, 바뀌지 않는 예상EPS만 가끔 넣으면")
    print("   선행PER이 매일 자동 계산됩니다.")
    print()
    print("   사용법:  python update_fwd_per.py --eps 890")
    print("   (예상EPS는 증권사 리포트·에프앤가이드·KB 등에서 월 1~2회만 확인)")
    print()
    print("   현재 예상EPS 추정치:  코스피지수 / 지금 쓰는 선행PER")
    try:
        k = pd.read_parquet(os.path.join(HERE, "krx_monthly.parquet"))["KOSPI_종가"]
        f = pd.read_parquet(os.path.join(HERE, "fwd_per_monthly.parquet"))["예상PER"]
        d = pd.concat([k, f], axis=1).dropna()
        if len(d):
            eps = d.iloc[-1, 0] / d.iloc[-1, 1]
            print(f"   → 최근 기준 약 {eps:,.0f}  (지수 {d.iloc[-1,0]:,.0f} / PER {d.iloc[-1,1]:.1f})")
    except Exception:
        pass
    sys.exit(0)

# 유효하면 전체 기간 수집
print("선행PER 유효 - 전체 기간 수집을 시작합니다.")
START = "20050101"
END = today.strftime("%Y%m%d")
try:
    df = stock.get_index_fundamental(START, END, KOSPI_TICKER, freq="m")
except TypeError:
    df = stock.get_index_fundamental(START, END, KOSPI_TICKER)

s = pd.to_numeric(df["선행PER"], errors="coerce")
s = s[s > 0]
s.index = pd.to_datetime(s.index)
s = s.resample("ME").last().dropna()
s.name = "예상PER"

if CHECK_ONLY:
    print(f"\n[진단모드] 저장하지 않습니다. 수집 가능 표본 {len(s)}개")
    print(s.tail(6).round(2).to_string())
    sys.exit(0)

out = os.path.join(HERE, "fwd_per_monthly.parquet")
# 기존 수동 입력분과 병합 (자동값 우선)
try:
    old = pd.read_parquet(out)["예상PER"]
    merged = s.combine_first(old).sort_index()
except Exception:
    merged = s.sort_index()

merged.to_frame().to_parquet(out)
print(f"\n저장 완료 → fwd_per_monthly.parquet")
print(f"  {merged.index[0].date()} ~ {merged.index[-1].date()}  ({len(merged)}개월)")
print(merged.tail(6).round(2).to_string())
print("\n이제 build_dashboard.py 를 실행하면 반영됩니다.")
