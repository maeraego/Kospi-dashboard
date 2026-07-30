# -*- coding: utf-8 -*-
"""점수구간별 기대수익 사다리 진단 — 단조성·구간개수·표본 확인."""
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

for ix in ['KOSPI', 'KOSDAQ']:
    print("=" * 60)
    print(f"  {ix} 점수구간별 12개월 기대수익")
    print("=" * 60)
    a = m.analyze(ix)
    # 실제 구간 개수 확인
    score = a['sc']
    def fwd(h):
        P = m.df[f'{ix}_종가']; return np.log(P.shift(-h) / P)
    xy = pd.concat([score.rename('s'), fwd(12).rename('y')], axis=1, sort=True).dropna()
    b, edges = pd.qcut(xy['s'], 5, labels=False, duplicates='drop', retbins=True)
    xy['b'] = b
    nb = xy['b'].nunique()
    print(f"  실제 구간 개수: {nb}개 (5개여야 정상)")
    print(f"  구간 경계: {[round(e,3) for e in edges]}")
    print()
    labs = ['최하위', '하위', '중위', '상위', '최상위']
    means = []
    for bb in sorted(xy['b'].unique()):
        g = xy[xy['b'] == bb]['y']
        lab = labs[int(bb)] if nb == 5 else f'구간{int(bb)}'
        here = ' ← 현재' if int(bb) == a['cbin'] else ''
        print(f"  {lab}: 평균 {g.mean():+.1%}  승률 {(g>0).mean():.0%}  표본 {len(g)}{here}")
        means.append(g.mean())
    mono = all(means[i] <= means[i+1] for i in range(len(means)-1))
    print(f"\n  단조 증가? {mono}  {'✓' if mono else '✗ 역전 있음!'}")
    print()
