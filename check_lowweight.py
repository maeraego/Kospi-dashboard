# -*- coding: utf-8 -*-
"""한국VIX·일드갭·VIX급등이 왜 가중이 낮은지 진단.
   IC / 평균상관(벌점) / Ridge계수 를 봐서 원인이 벌점인지 Ridge인지 판별."""
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
    xx = pd.concat([ez(s2) * b, y], axis=1, sort=True).dropna()
    r = xx.iloc[:, 0].corr(xx.iloc[:, 1]) if len(xx) > 40 else 0
    Z[n] = ez(s2) * (b if r >= 0 else -b)
Z = pd.DataFrame(Z).ffill(limit=3)
keep = [c for c in Z.columns if ic.get(c, 0) >= 0.10 and c != '시가총액/M2']
C = Z[keep].corr().abs()

# Ridge 계수
D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
X = D[keep].values; sd = X.std(0); sd[sd == 0] = 1
Xs = (X - X.mean(0)) / sd; yy = D['_y'].values - D['_y'].mean()
G = Xs.T @ Xs; bb = Xs.T @ yy
betas = [np.abs(np.linalg.solve(G + lam*np.eye(len(keep)), bb)) for lam in (10, 30, 100)]
beta = pd.Series(np.mean(betas, axis=0), index=keep)

print(f"{'신호':16s} {'IC':>6s} {'평균상관':>7s} {'Ridge계수':>9s} {'IC×Ridge':>9s} {'벌점후':>7s}")
for n in keep:
    ac = (C[n].sum() - 1) / (len(keep) - 1)
    icr = ic[n] * beta[n]
    pen = icr / (1 + 1.0 * ac)
    mark = ''
    if n in ['한국VIX', '일드갭 (예상PER)', 'VIX 급등(YoY)', '경기선행지수', '기준금리 YoY']:
        mark = ' ★'
    print(f"  {n:14s} {ic[n]:6.3f} {ac:7.3f} {beta[n]:9.3f} {icr:9.4f} {pen:7.4f}{mark}")

print()
print("★ = 민용님이 지적한 신호")
print("판별: 평균상관 높으면 벌점탓 / Ridge계수 낮으면 Ridge탓")
