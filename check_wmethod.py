# -*- coding: utf-8 -*-
"""가중치 방법 비교: 순수 Ridge vs IC×Ridge 혼합 vs 순수 IC.

억제변수(IC 낮은데 가중 높은 신호) 문제를 어느 방법이 잘 푸는지,
그리고 표본외 성능이 유지되는지 검증한다.
"""
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

ix = 'KOSPI'
df = m.df
def ez(s, mp=36): return (s - s.expanding(mp).mean()) / s.expanding(mp).std()
def fwd(h=12):
    P = df[f'{ix}_종가']; return np.log(P.shift(-h) / P)
y = fwd(12)

# 신호 구성 (build_dashboard와 동일하게)
sig = m.signals_for(ix)
Z, IC = {}, {}
for t in sig:
    n, s_, base = t[0], t[1], t[2]
    xx = pd.concat([ez(s_) * base, y], axis=1, sort=True).dropna()
    r = xx.iloc[:, 0].corr(xx.iloc[:, 1]) if len(xx) > 40 else 0
    Z[n] = ez(s_) * (base if r >= 0 else -base)
    IC[n] = abs(r)
Z = pd.DataFrame(Z).ffill(limit=3)
REF = {'시가총액/M2'}
keep = [c for c in Z.columns if IC[c] >= 0.10 and c not in REF]

def ridge_w(cols, tr):
    X = tr[cols].values; sd = X.std(0); sd[sd == 0] = 1
    Xs = (X - X.mean(0)) / sd; yy = tr['_y'].values - tr['_y'].mean()
    G = Xs.T @ Xs; b = Xs.T @ yy
    Ws = []
    for lam in (10, 30, 100):
        beta = np.linalg.solve(G + lam*np.eye(len(cols)), b)
        aa = np.abs(beta); 
        if aa.sum() > 0: Ws.append(aa/aa.sum())
    return pd.Series(np.mean(Ws, axis=0), index=cols)

def oos(method):
    D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
    tr = D[D.index <= '2015']; te = D[D.index > '2015']
    if len(tr) < 40 or len(te) < 20: return None, None
    rw = ridge_w(keep, tr)
    if method == 'ridge':
        w = rw
    elif method == 'ic':
        w = pd.Series({c: IC[c] for c in keep})
    elif method == 'mix':          # IC × Ridge
        w = pd.Series({c: IC[c] * rw[c] for c in keep})
    w = w / w.sum()
    ic_oos = (te[keep] * w).sum(axis=1).corr(te['_y'])
    return w, ic_oos

print("=" * 64)
print("  가중치 방법별 비교")
print("=" * 64)
results = {}
for method, lab in [('ridge', '순수 Ridge (현재)'), ('ic', '순수 IC'), ('mix', 'IC×Ridge 혼합')]:
    w, ic_oos = oos(method)
    results[method] = (w, ic_oos)
    print(f"\n  [{lab}]  표본외 IC = {ic_oos:+.3f}")
    for n in w.sort_values(ascending=False).index[:6]:
        print(f"    {n:16s} {w[n]*100:5.1f}%  (단독IC {IC[n]:.3f})")

print()
print("=" * 64)
print("  억제변수 점검: 일드커브·기준금리 가중 변화")
print("=" * 64)
for n in ['일드커브', '기준금리', '경기선행지수', 'PBR', '예상PER 괴리']:
    if n not in keep: continue
    r = results['ridge'][0].get(n, 0) * 100
    mx = results['mix'][0].get(n, 0) * 100
    print(f"  {n:16s} Ridge {r:5.1f}%  →  혼합 {mx:5.1f}%  ({mx-r:+.1f})")
