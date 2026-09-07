# -*- coding: utf-8 -*-
"""
check_lookahead.py  -  발표시차 미반영(룩어헤드) 영향 측정

월간 매크로 지표는 '참조월' 기준으로 저장되지만 실제 발표는 1~3개월 뒤다.
예) 2026-07 경기선행지수는 2026-09 하순에 발표된다.
그런데 신호는 2026-07-31 시점에 그 값을 알고 있는 것처럼 쓰고 있다.
즉 백테스트가 미래 정보를 쓴 셈이라 IC가 부풀려질 수 있다.

지표별로 발표시차만큼 shift 한 뒤 IC 와 표본외 성적이 얼마나 떨어지는지 잰다.

사용법:  C:/python312/python.exe check_lookahead.py
"""
import io, sys, contextlib
import numpy as np, pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with contextlib.redirect_stdout(io.StringIO()):
    import build_dashboard as bd
df, ez = bd.df, bd.ez

# 실제 발표시차(개월). ECOS/통계청 공표 관행 기준.
LAG = {'경기선행지수': 2, '예상PER 괴리': 2, '선행 PBR': 2,
       '일드갭 (예상PER)': 2, '수출 YoY': 2, 'M2 증가율(YoY)': 3,
       'M2/M1 비율': 3, '채산성(CPI-PPI)': 2}


def ic_of(s, base, y):
    x = pd.concat([ez(s) * base, y], axis=1, sort=True).dropna()
    return (abs(float(x.iloc[:, 0].corr(x.iloc[:, 1]))), len(x)) if len(x) > 40 else (0.0, len(x))


for ix in ('KOSPI', 'KOSDAQ'):
    a = bd.analyze(ix)
    w, y = a['w'], np.log(df[f'{ix}_종가'].shift(-12) / df[f'{ix}_종가'])
    print('=' * 74)
    print(f'{ix}  발표시차 반영 전후 단독 IC')
    print('=' * 74)
    print(f'{"신호":20s} {"가중":>6s} {"시차":>4s} {"IC(현행)":>9s} {"IC(시차반영)":>11s} {"변화":>8s}')
    tot = 0.0
    for item in bd.signals_for(ix):
        nm, raw, base = item[0], item[1], item[2]
        if nm not in LAG or raw is None:
            continue
        s = pd.Series(raw).astype(float)
        i0, _ = ic_of(s, base, y)
        i1, _ = ic_of(s.shift(LAG[nm]), base, y)
        wt = w.get(nm, 0.0)
        flag = ''
        if wt > 0 and i1 < 0.10 <= i0:
            flag = '  ← 필터 탈락'
        print(f'{nm:20s} {wt*100:5.1f}% {LAG[nm]:3d}월 {i0:9.3f} {i1:11.3f} {i1-i0:+8.3f}{flag}')
        tot += wt
    print(f'  영향 받는 가중 합계 {tot*100:.1f}%')
    print()
