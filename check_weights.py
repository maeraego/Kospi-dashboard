# -*- coding: utf-8 -*-
"""가중치 방법론 진단: 경기선행/금리 vs 가치지표(PER/PBR/예상PER).

민용님 질문:
  2. 경기선행지수 가중치가 너무 높지 않나?
  3. 금리·금리YoY도 너무 높지 않나?
  4. 오히려 PER/PBR/예상PER이 더 높아야 하지 않나?

세 가지를 데이터로 검증:
  (A) 각 신호의 단독 IC (진짜 예측력)
  (B) 현재 Ridge 가중치
  (C) 신호 간 상관 (겹치면 가중이 갈림)
  (D) IC 순위 vs 가중 순위 비교 → 방법이 예측력을 반영하나?
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

for ix in ['KOSPI']:
    a = m.analyze(ix)
    print("=" * 68)
    print(f"  {ix}: 단독 IC(예측력) vs Ridge 가중치")
    print("=" * 68)
    rows = []
    for r in a['reads']:
        n, z, w = r[0], r[5], r[6]
        ic = a['ic'][n]
        rows.append((n, ic, w))
    # IC 순위와 가중 순위
    by_ic = sorted(rows, key=lambda x: -x[1])
    by_w = sorted(rows, key=lambda x: -x[2])
    ic_rank = {n: i+1 for i, (n, _, _) in enumerate(by_ic)}
    w_rank = {n: i+1 for i, (n, _, _) in enumerate(by_w)}
    print(f"  {'신호':16s} {'IC':>6s} {'IC순위':>6s} {'가중':>7s} {'가중순위':>7s} {'차이':>5s}")
    for n, ic, w in by_w:
        if w <= 0:
            continue
        gap = ic_rank[n] - w_rank[n]
        flag = ' ⚠' if abs(gap) >= 3 else ''
        print(f"  {n:16s} {ic:6.3f} {ic_rank[n]:5d}위 {w*100:6.1f}% {w_rank[n]:5d}위 {gap:+4d}{flag}")
    print()
    print("  ⚠ = IC순위와 가중순위가 3계단 이상 차이 (겹침·억제 때문)")
    print()

    # 가치지표 vs 매크로 그룹 비교
    val_names = ['PBR', 'PER', '예상PER 괴리', '일드갭 (예상PER)']
    macro_names = ['경기선행지수', '기준금리 YoY', '기준금리', '환율(원/달러)']
    print("  ── 그룹별 IC·가중 합계 ──")
    for gname, names in [('가치지표', val_names), ('매크로', macro_names)]:
        ics = [a['ic'][n] for n in names if n in a['ic']]
        ws = [a['w'].get(n, 0) for n in names]
        print(f"    {gname}: 평균 IC {np.mean(ics):.3f}, 가중합 {sum(ws)*100:.0f}%  ({', '.join(names)})")
    print()

    # 상관행렬: 가치지표끼리 얼마나 겹치나
    print("  ── 가치지표 간 상관 (높으면 서로 가중 갉아먹음) ──")
    def fwd(h=12):
        P = m.df[f'{ix}_종가']; return np.log(P.shift(-h) / P)
    def ez(s, mp=36): return (s - s.expanding(mp).mean()) / s.expanding(mp).std()
    cols = {}
    if 'KOSPI_PBR' in m.df: cols['PBR'] = ez(m.df['KOSPI_PBR'])
    if 'KOSPI_PER' in m.df: cols['PER'] = ez(m.df['KOSPI_PER'])
    if '예상PER' in m.df: cols['예상PER'] = ez(np.log(m.df['예상PER']))
    C = pd.DataFrame(cols).corr()
    print(C.round(2).to_string())
