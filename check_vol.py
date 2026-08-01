# -*- coding: utf-8 -*-
"""변동성 지표(한국VIX·VIX급등)에 최소가중 부여시 표본외 영향 검증.
   + 지금 같은 급락장(현재 시점)을 모델이 제대로 '불리'로 잡는지 확인."""
import io, contextlib, importlib.util, sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(m)
df = m.df
def ez(s, mp=36): return (s - s.expanding(mp).mean()) / s.expanding(mp).std()
P = df['KOSPI_종가']; y = np.log(P.shift(-12) / P)

a = m.analyze('KOSPI')
ic = a['ic']
sig = m.signals_for('KOSPI')
Z = {}
for t in sig:
    n, s2, b = t[0], t[1], t[2]
    xx = pd.concat([ez(s2)*b, y], axis=1, sort=True).dropna()
    r = xx.iloc[:,0].corr(xx.iloc[:,1]) if len(xx) > 40 else 0
    Z[n] = ez(s2) * (b if r >= 0 else -b)
Z = pd.DataFrame(Z).ffill(limit=3)
keep = [c for c in Z.columns if ic.get(c,0) >= 0.10 and c != '시가총액/M2']

# 현재 가중 (build_dashboard와 동일 로직 근사)
w0 = {c: a['w'].get(c, 0) for c in keep}
tot = sum(w0.values())
w0 = {c: v/tot for c, v in w0.items()}

VOL = ['한국VIX', 'VIX 급등(YoY)']
D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
tr = D[D.index <= '2015']; te = D[D.index > '2015']

def oos(wd):
    ws = pd.Series(wd); ws = ws / ws.sum()
    return (te[keep] * ws).sum(axis=1).corr(te['_y'])

print("=== 변동성 지표 최소가중 부여 시 표본외 IC ===")
print(f"  현재 가중: 표본외 {oos(w0):+.3f}")
for floor in [0.03, 0.05, 0.08]:
    wd = dict(w0)
    for v in VOL:
        if v in wd: wd[v] = max(wd[v], floor)
    print(f"  변동성 하한 {floor*100:.0f}%: 표본외 {oos(wd):+.3f}  (한국VIX {wd.get('한국VIX',0)*100:.0f}%)")

print()
print("=== 지금 급락장을 각 방식이 어떻게 판정하나 ===")
cur_z = {r[0]: r[5] for r in a['reads'] if r[5] is not None}
print(f"  한국VIX 현재 z: {cur_z.get('한국VIX', 0):+.2f}")
print(f"  현재 종합점수(현행): {a['cur']:+.3f}")
# 변동성 하한 적용시 점수 재계산
for floor in [0.05, 0.08]:
    wd = dict(w0)
    for v in VOL:
        if v in wd: wd[v] = max(wd[v], floor)
    tot = sum(wd.values()); wd = {c: v/tot for c, v in wd.items()}
    newscore = sum(cur_z.get(c, 0) * wd[c] for c in keep if c in cur_z)
    print(f"  변동성 하한 {floor*100:.0f}% 적용시 점수: {newscore:+.3f}")
