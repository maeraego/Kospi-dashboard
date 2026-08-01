# -*- coding: utf-8 -*-
"""예측 밴드가 왜 그렇게 나오는지 진단."""
import io, contextlib, importlib.util, sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(m)

a = m.analyze('KOSPI')
pj = a['proj']
px = pj['px']
print("=== 현재 예측 밴드 ===")
print(f"현재가:      {px:,.0f}")
print(f"예측 하단:   {pj['lo']:,.0f}  ({pj['lo']/px-1:+.0%})")
print(f"예측 중앙:   {pj['med']:,.0f}  ({pj['med']/px-1:+.0%})")
print(f"예측 상단:   {pj['hi']:,.0f}  ({pj['hi']/px-1:+.0%})")
print(f"종합점수:    {a['cur']:+.2f}  (cbin {a['cbin']})")
print()

# 현재 국면의 과거 12개월 수익 분포
df = m.df
P = df['KOSPI_종가']
fwd = np.log(P.shift(-12)/P).dropna()
score = a['sc']
xy = pd.concat([score.rename('s'), fwd.rename('y')], axis=1, sort=True).dropna()
xy['b'] = np.clip((xy['s'].rank(pct=True)*10).astype(int).clip(0,9),0,9)
g = xy[xy['b']==a['cbin']]['y']
print(f"=== 현재 국면(cbin={a['cbin']})의 과거 12개월 수익 ===")
print(f"표본 수: {len(g)}")
print(f"  최악: {(np.exp(g.min())-1)*100:+.0f}%")
print(f"  15%분위: {(np.exp(g.quantile(.15))-1)*100:+.0f}%")
print(f"  중앙: {(np.exp(g.median())-1)*100:+.0f}%")
print(f"  85%분위: {(np.exp(g.quantile(.85))-1)*100:+.0f}%")
print(f"  최고: {(np.exp(g.max())-1)*100:+.0f}%")
print()
print("이 국면에 속했던 과거 시기들의 실제 12개월 수익:")
for t, v in g.sort_values().items():
    print(f"  {t.date()}: {(np.exp(v)-1)*100:+.0f}%")
