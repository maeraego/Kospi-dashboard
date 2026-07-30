# -*- coding: utf-8 -*-
"""예측 중앙값(7200→6200) 변화 원인 진단."""
import io, contextlib, importlib.util, sys, os
import numpy as np, pandas as pd
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m)

a = m.analyze('KOSPI')
pj = a['proj']
print("=" * 60)
print("  KOSPI 12개월 예측 진단")
print("=" * 60)
print(f"  현재가:        {pj['px']:,.0f}")
print(f"  예측 중앙값:   {pj['med']:,.0f}  ({(pj['med']/pj['px']-1)*100:+.1f}%)")
print(f"  70% 범위:      {pj['lo']:,.0f} ~ {pj['hi']:,.0f}")
print()
print(f"  현재 종합점수: {a['cur']:+.3f}")
print(f"  현재 국면(cbin): {a['cbin']} ({['최하위','하위','중위','상위','최상위'][a['cbin']]})")
print(f"  이 국면 표본수: {a['tbl']['n12']}")
print()
print("  ★ 중앙값이 현재가보다 낮은 이유:")
print(f"     현재 '{['최하위','하위','중위','상위','최상위'][a['cbin']]}' 국면의")
print(f"     과거 12개월 실제수익 중앙값 = {(pj['med']/pj['px']-1)*100:+.1f}%")
print()
# 각 신호가 점수에 얼마나 기여하는지
print("  현재 점수를 만든 신호별 기여 (z × 가중):")
contrib = []
for r in a['reads']:
    n, z, w = r[0], r[5], r[6]
    if z is None or w <= 0:
        continue
    contrib.append((n, z * w, z, w))
contrib.sort(key=lambda x: -abs(x[1]))
for n, c, z, w in contrib:
    sign = '↑강세' if c > 0 else '↓약세'
    print(f"    {n:16s} {c:+.4f}  ({sign}, z={z:+.2f} × {w*100:.0f}%)")
print()
print(f"  합계(종합점수): {sum(c for _, c, _, _ in contrib):+.3f}")
print()
print("  → 점수가 낮으면(불리) → 낮은 국면 → 그 국면 과거수익 중앙값이")
print("     마이너스 → 예측 중앙값이 현재가보다 낮게 나옴 (정상 로직)")
