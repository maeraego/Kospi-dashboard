# -*- coding: utf-8 -*-
"""시가총액/M2 신호가 진짜인지 정밀 검증."""
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

def ic_detail(x, lab):
    xy = pd.concat([x.rename('x'), y.rename('y')], axis=1, sort=True).dropna()
    if len(xy) < 40:
        print(f"  {lab}: 표본 부족 {len(xy)}"); return
    full = xy['x'].corr(xy['y'])
    # 시기별 안정성
    xy = xy.sort_index()
    h1 = xy[xy.index <= '2015']; h2 = xy[xy.index > '2015']
    ic1 = h1['x'].corr(h1['y']) if len(h1) > 20 else float('nan')
    ic2 = h2['x'].corr(h2['y']) if len(h2) > 20 else float('nan')
    print(f"  {lab:26s} 전체 {full:+.3f} | 전반 {ic1:+.3f} | 후반 {ic2:+.3f} | n={len(xy)}")

print("=" * 66)
print("  시가총액/M2 정밀 검증")
print("=" * 66)
print("\n[1] IC 안정성 (전반/후반이 크게 다르면 불안정)")
ic_detail(ez(mc_m2) * -1, '시가총액/M2 (z, -1)')
ic_detail(ez(df['KOSPI_PBR']) * -1, 'PBR (비교용)')

print("\n[2] M2가 2003년부터라 표본이 23년뿐 — 다른 신호와 기간 불일치 확인")
print(f"    시총/M2 유효구간: {mc_m2.dropna().index[0].date()} ~ {mc_m2.dropna().index[-1].date()}")
print(f"    PBR 유효구간:     {df['KOSPI_PBR'].dropna().index[0].date()} ~")

print("\n[3] 현재값이 정말 역대 최고인가 (착시 아닌지)")
cur = mc_m2.dropna().iloc[-1]
pct = (mc_m2.dropna() < cur).mean()
print(f"    현재 시총/M2 = {cur:.3f}, 백분위 {pct*100:.0f}%")
print(f"    과거 최고 5개: {mc_m2.dropna().nlargest(5).round(3).to_dict()}")

print("\n[4] 코스피 상승이 M2보다 빨라서 생긴 착시? — 최근 3년 추세")
recent = mc_m2.dropna().tail(36)
print(f"    3년 전 {recent.iloc[0]:.3f} → 현재 {recent.iloc[-1]:.3f} "
      f"({(recent.iloc[-1]/recent.iloc[0]-1)*100:+.0f}%)")

print("\n[5] 이 신호 하나 뺐을 때 표본외 성능 변화 (실제 기여도)")
def ez2(s, mp=36): return (s - s.expanding(mp).mean()) / s.expanding(mp).std()
sig = m.signals_for('KOSPI'); Z = {}; IC = {}
for n, s_, base, *_ in sig:
    xx = pd.concat([ez2(s_) * base, y], axis=1, sort=True).dropna()
    r = xx.iloc[:, 0].corr(xx.iloc[:, 1]) if len(xx) > 40 else 0
    Z[n] = ez2(s_) * (base if r >= 0 else -base); IC[n] = abs(r)
Z = pd.DataFrame(Z).ffill(limit=3)
keep = [c for c in Z.columns if IC[c] >= 0.10]
def oos(cols):
    D = pd.concat([Z[cols], y.rename('y')], axis=1, sort=True).dropna()
    tr = D[D.index <= '2015']; te = D[D.index > '2015']
    if len(tr) < 40 or len(te) < 20: return float('nan')
    w = m._ridge_weights(tr[cols], tr['y'], cols)
    return (te[cols] * w).sum(axis=1).corr(te['y']) if w is not None else float('nan')
has = '시가총액/M2' in keep
print(f"    시총/M2 포함:  {oos(keep):+.3f}")
print(f"    시총/M2 제외:  {oos([c for c in keep if c != '시가총액/M2']):+.3f}")
