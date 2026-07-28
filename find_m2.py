# -*- coding: utf-8 -*-
"""
find_m2.py — 신지표 M1/M2 표코드 확정 (최종).

구지표(101Y001~019)는 2004년에 끝난다. 신지표는 '1.1. 통화/유동성(신지표)'(0000000620)
하위에 있다. 두 갈래로 찾는다:
  (A) 100대 통계(KeyStatisticList)에서 M2를 찾으면 그 STAT_CODE가 곧 답.
  (B) 안 되면 넓은 코드 대역(103Y~110Y 등)을 훑어 2025년 값이 오는 M2 표를 찾는다.

사용:  C:/python312/python.exe find_m2.py
"""
import os
import sys
import requests

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

KEY = os.environ.get('ECOS_KEY')
if not KEY:
    print("[중단] ECOS_KEY 없음"); sys.exit(1)
BASE = "https://ecos.bok.or.kr/api"


def get(url):
    try:
        return requests.get(url, timeout=25).json()
    except Exception as e:
        return {"_err": str(e)}


# ── (A) 100대 주요 통계에서 M2 찾기 ─────────────────────────
print("=" * 70)
print("  (A) 100대 주요통계 — M1/M2 항목의 전체 필드(표코드 확인)")
print("=" * 70)
j = get(f"{BASE}/KeyStatisticList/{KEY}/json/kr/1/100")
b = j.get("KeyStatisticList", {})
rows = b.get("row", []) if isinstance(b, dict) else []
for r in rows:
    cls = r.get("CLASS_NAME", "")
    name = r.get("KEYSTAT_NAME", "")
    if any(k in (cls + name) for k in ("통화", "M1", "M2", "유동성")):
        # 전체 필드를 그대로 출력해 표코드 필드명을 확인
        print(f"\n  ── {cls} | {name} = {r.get('DATA_VALUE')} ──")
        for k, v in r.items():
            print(f"      {k} = {v}")

# ── (B) (A)에서 얻은 STAT_CODE로 M2 시계열을 직접 조회 검증 ──
print("\n" + "=" * 70)
print("  (B) 위에서 확인된 표코드로 M2 전체 시계열 조회 (1995~2026)")
print("=" * 70)
# (A) 출력에서 STAT_CODE/ITEM_CODE 필드를 찾아 자동 시도
m2row = None
for r in rows:
    nm = r.get("CLASS_NAME", "") + r.get("KEYSTAT_NAME", "")
    if "M2" in nm:
        m2row = r; break
if m2row:
    stat = (m2row.get("STAT_CODE") or m2row.get("P_STAT_CODE")
            or m2row.get("STAT_CD") or "")
    item = (m2row.get("ITEM_CODE") or m2row.get("ITEM_CODE1")
            or m2row.get("ITEM_CD") or "")
    cyc = m2row.get("CYCLE", "M")
    cyc = "M" if str(cyc).startswith("20") else (cyc or "M")
    print(f"  시도: STAT={stat}  ITEM={item}  CYCLE=M")
    if stat and item:
        jj = get(f"{BASE}/StatisticSearch/{KEY}/json/kr/1/5/{stat}/M/202501/202512/{item}")
        bb = jj.get("StatisticSearch", {})
        rr = bb.get("row", []) if isinstance(bb, dict) else []
        if rr:
            print(f"  ✅ 성공! {stat}/{item} 로 M2 조회됨. 최근: {rr[-1].get('TIME')}={rr[-1].get('DATA_VALUE')}")
            print(f"\n  → collect_ecos.py 에 이 코드를 박으면 됩니다:")
            print(f"     STAT_CODE = '{stat}'   ITEM_CODE = '{item}'")
        else:
            print(f"  조회 실패. 위 (A)의 전체 필드에서 STAT_CODE/ITEM_CODE 값을 확인하세요.")
    else:
        print("  STAT_CODE/ITEM_CODE 필드가 위 (A) 출력에 있습니다. 그 값을 알려주세요.")
else:
    print("  M2 행을 못 찾음.")



