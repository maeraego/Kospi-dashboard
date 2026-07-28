# -*- coding: utf-8 -*-
"""
collect_ecos.py  —  한국은행 ECOS 국내 매크로 수집기
사용법:  C:/python312/python.exe collect_ecos.py
필요:    .env 에  ECOS_KEY=발급받은키   (같은 폴더)
출력:    ecos_daily.parquet, ecos_monthly.parquet

설계 메모:
  항목코드(item_code)를 하드코딩하지 않고, 실행 시점에 통계표의
  항목 목록을 받아 '이름'으로 자동 매칭한다. 무엇을 집었는지 로그로
  전부 출력하므로, 틀리면 바로 눈으로 확인/수정 가능.
"""
import os, sys, time, json, re
from datetime import datetime
import urllib.request
import pandas as pd

# ---- credentials ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

KEY = os.environ.get("ECOS_KEY")
if not KEY:
    print("[중단] ECOS_KEY 가 설정되지 않았습니다.  .env 에  ECOS_KEY=...  를 넣으세요.")
    print("       (python-dotenv 미설치 시:  C:/python312/python.exe -m pip install python-dotenv)")
    sys.exit(1)
print(f"[인증] ECOS_KEY = {KEY[:4]}***  (감지됨)")

BASE   = "https://ecos.bok.or.kr/api"
TODAY  = datetime.today()
START_D, END_D = "19950101", TODAY.strftime("%Y%m%d")   # 매크로는 1995년부터
START_M, END_M = "199501",   TODAY.strftime("%Y%m")

def _get(url, retries=4):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = str(e); time.sleep(1.5 * (i + 1))
    raise RuntimeError(last)

def item_list(stat_code):
    d = _get(f"{BASE}/StatisticItemList/{KEY}/json/kr/1/1000/{stat_code}")
    return d.get("StatisticItemList", {}).get("row", []) or []

def pick_item(stat_code, patterns):
    """통계표 항목 중 patterns(정규식 리스트) 첫 매치의 (code, name) 반환."""
    rows = item_list(stat_code)
    for pat in patterns:
        rx = re.compile(pat)
        for r in rows:
            nm = r.get("ITEM_NAME1") or r.get("ITEM_NAME") or ""
            if rx.search(nm):
                return r.get("ITEM_CODE") or r.get("ITEM_CODE1"), nm, rows
    return None, None, rows

def search(stat_code, cycle, start, end, item_code):
    url = f"{BASE}/StatisticSearch/{KEY}/json/kr/1/100000/{stat_code}/{cycle}/{start}/{end}/{item_code}"
    d = _get(url)
    if "StatisticSearch" not in d:
        return None, d.get("RESULT", {})
    return d["StatisticSearch"]["row"], None

def to_series(rows, cycle):
    idx, val = [], []
    for r in rows:
        t = r["TIME"]; v = r["DATA_VALUE"]
        if v in ("", None): continue
        if cycle == "D":
            ts = pd.Timestamp(f"{t[:4]}-{t[4:6]}-{t[6:8]}")
        else:  # M
            ts = pd.Timestamp(f"{t[:4]}-{t[4:6]}-01") + pd.offsets.MonthEnd(0)
        idx.append(ts); val.append(float(v))
    return pd.Series(val, index=idx).sort_index()

def collect(label, stat_code, cycle, patterns):
    start, end = (START_D, END_D) if cycle == "D" else (START_M, END_M)
    code, name, rows = pick_item(stat_code, patterns)
    if code is None:
        print(f"  x {label:14s}  항목 매칭 실패 @ {stat_code}. 후보 항목:")
        for r in rows[:12]:
            nm = r.get("ITEM_NAME1") or r.get("ITEM_NAME") or ""
            print(f"        - {r.get('ITEM_CODE') or r.get('ITEM_CODE1')}  {nm}")
        return None
    rws, err = search(stat_code, cycle, start, end, code)
    if rws is None:
        print(f"  x {label:14s}  조회 실패 @ {stat_code}/{code}: {err}")
        return None
    s = to_series(rws, cycle)
    print(f"  · {label:14s}  <- {stat_code}/{code} '{name}' ({cycle})  {s.index[0].date()}~{s.index[-1].date()} n={len(s)}")
    time.sleep(0.35)
    return s

# ── 수집 대상 (통계표코드는 표 단위, 항목은 이름으로 자동 매칭) ──
print(f"[수집] {START_D} ~ {END_D}\n")
S = {}

# 기준금리 (722Y001: 한국은행 기준금리·여수신금리 표)
S["기준금리"]     = collect("기준금리",     "722Y001", "D", [r"한국은행\s*기준금리", r"기준금리"])

# 시장금리 (817Y002: 시장금리 일별 — 국고채/회사채/CD)
S["국고채3년"]    = collect("국고채3년",    "817Y002", "D", [r"국고채.*3년"])
S["국고채10년"]   = collect("국고채10년",   "817Y002", "D", [r"국고채.*10년"])
S["회사채3년AA"]  = collect("회사채3년AA-", "817Y002", "D", [r"회사채.*3년.*AA-?", r"회사채.*AA-?"])
S["CD91"]        = collect("CD(91일)",     "817Y002", "D", [r"CD.*91", r"양도성예금증서.*91"])

# 환율 (731Y001)
S["원달러"]       = collect("원/달러",      "731Y001", "D", [r"원/미국달러", r"미국\s*달러", r"원/달러"])

# 경기선행지수 (901Y067: 경기종합지수, 월별)
S["선행지수"]     = collect("선행지수순환", "901Y067", "M", [r"선행지수순환변동치", r"선행종합지수"])

# 수출 (901Y118: 수출입 총괄 통관 수출액 / 403Y001: 수출금액지수)  — 둘 다 월별
S["수출금액"]     = collect("수출금액통관", "901Y118", "M", [r"수출금액", r"수출액", r"^수출(?!입)"])
S["수출금액지수"] = collect("수출금액지수", "403Y001", "M", [r"총지수", r"수출금액지수", r"^수출"])
S["무역수지"]     = collect("무역수지순수출", "901Y118", "M", [r"무역수지", r"수지", r"순수출"])

# 통화량 (101Y002 표: 통화 및 유동성 총량 지표, 월별)
#   로그에서 확인된 실제 항목:
#     BBGA00 = M2(말잔, 원계열)   ← 2004년에 끊기는 계절조정계열(101Y003) 대신 이걸 쓴다
#     BBGA01 = 현금통화 / BBGA02 = 요구불예금 / BBGA03 = 수시입출식저축성예금
#   M1(협의통화) = 현금통화 + 요구불예금 + 수시입출식저축성예금
#   M2/M1 비율 = 유동성 회전속도. M2 증가율 = 대표 경기 선행지표.
_cash = collect("현금통화",   "101Y002", "M", [r"현금통화"])
_dd   = collect("요구불예금",  "101Y002", "M", [r"요구불예금"])
_mmda = collect("수시입출식",  "101Y002", "M", [r"수시입출식"])
if _cash is not None and _dd is not None and _mmda is not None:
    S["M1"] = (_cash.add(_dd, fill_value=0).add(_mmda, fill_value=0)).rename("M1")
    print(f"  · M1(합성)       <- 현금통화+요구불예금+수시입출식  n={S['M1'].dropna().shape[0]}")
S["M2"] = collect("M2광의통화", "101Y002", "M", [r"M2\(말잔,\s*원계열\)", r"M2\(말잔", r"M2.*원계열", r"^M2"])

# ── 정리/파생 ──
S = {k: v for k, v in S.items() if v is not None}
if not S:
    print("\n[중단] 수집된 시리즈가 없습니다.")
    sys.exit(1)

MONTHLY_KEYS = {"선행지수", "수출금액", "수출금액지수", "무역수지", "M1", "M2"}  # 월별 네이티브

# 일별 프레임(일별 시리즈만)
daily_keys = [k for k in S if k not in MONTHLY_KEYS]
daily = pd.DataFrame({k: S[k] for k in daily_keys}).sort_index()
daily.index.name = "date"

# 신용스프레드 = 회사채(3년,AA-) - 국고채(3년)
if "회사채3년AA" in daily and "국고채3년" in daily:
    daily["신용스프레드"] = daily["회사채3년AA"] - daily["국고채3년"]
    print("  + 신용스프레드 = 회사채3년AA- − 국고채3년  파생 생성")

# 월간 = 일별 월말 + 월별네이티브 조인
monthly = daily.resample("ME").last()
for k in MONTHLY_KEYS:
    if k in S:
        monthly = monthly.join(S[k].rename(k), how="outer")
monthly.index.name = "date"

daily.to_parquet("ecos_daily.parquet")
monthly.to_parquet("ecos_monthly.parquet")

print("\n" + "=" * 56)
print(f"일별 : {daily.index[0].date()} ~ {daily.index[-1].date()}  ({len(daily)} rows)")
print(f"월간 : {monthly.index[0].date()} ~ {monthly.index[-1].date()}  ({len(monthly)} rows)")
print("컬럼별 유효 데이터 시작:")
for c in monthly.columns:
    s = monthly[c].dropna()
    if len(s):
        print(f"   {c:12s}: {s.index[0].date()}  (n={len(s)})")
print("=" * 56)
print("저장 완료 → ecos_daily.parquet, ecos_monthly.parquet")
