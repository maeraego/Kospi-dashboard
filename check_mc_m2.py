# -*- coding: utf-8 -*-
"""시가총액/M2 가 순환참조인지 진짜 밸류 신호인지 검증."""
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
df = m.df

def ez(s, mp=36):
    return (s - s.expanding(mp).mean()) / s.expanding(mp).std()
def fwd(h=12):
    P = df['KOSPI_종가']; return np.log(P.shift(-h) / P)
y = fwd(12)

mc_m2 = df['KOSPI_시총'] / df['M2']
pbr = df['KOSPI_PBR']
mom = df['KOSPI_종가'].pct_change(12)

def ic(x):
    xy = pd.concat([x.rename('x'), y.rename('y')], axis=1, sort=True).dropna()
    return xy['x'].corr(xy['y']), len(xy)

print("=== 시가총액/M2 vs 다른 밸류/모멘텀 신호 ===")
for nm, x, d in [('시가총액/M2', ez(mc_m2), -1),
                 ('PBR', ez(pbr), -1),
                 ('코스피 모멘텀(과거12M)', ez(mom), -1)]:
    c, n = ic(x * d)
    print(f"  {nm:22s} IC {c:+.3f}  n={n}")

# 시총/M2에서 코스피 모멘텀 성분 제거 후에도 예측력 남나?
c = pd.concat([mc_m2.rename('v'), mom.rename('m')], axis=1, sort=True).dropna()
rv, rm = c['v'].rank(pct=True), c['m'].rank(pct=True)
resid = rv - np.polyfit(rm, rv, 1)[0] * rm
cc, nn = ic(ez(resid) * -1)
print(f"\n  시총/M2에서 코스피 모멘텀 제거 후: IC {cc:+.3f}")
print("  → 0에 가까우면 '코스피 재탕', 유의미하면 '진짜 밸류 정보'")

# 시총/M2 vs PBR 상관 (같은 얘기 하는지)
c2 = pd.concat([mc_m2.rename('a'), pbr.rename('b')], axis=1, sort=True).dropna()
print(f"\n  시총/M2 ↔ PBR 상관: {c2['a'].corr(c2['b']):+.3f}")
print("  (너무 높으면 PBR과 중복, 적당하면 독립적 정보 추가)")
