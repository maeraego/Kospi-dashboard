# -*- coding: utf-8 -*-
"""
check_newsig.py  -  신규 후보 신호의 편입 가능 여부 판정

후보: 채산성(CPI YoY − PPI YoY), 일본10년, 원/엔, 원/위안
판정 기준(CLAUDE.md 파이프라인과 동일):
   |IC| >= 0.10  &  관측 >= 60  ->  가중 후보
   그 미만이면 REF_ONLY(차트만)
추가로 CCF 로 선후행을 보고, 기존 신호와의 상관으로 중복을 본다.

사용법:  C:/python312/python.exe check_newsig.py
"""
import io, sys, contextlib
import numpy as np, pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_b = io.StringIO()
with contextlib.redirect_stdout(_b):
    import build_dashboard as bd
df = bd.df


def sp(a, b):
    """순위상관(스피어만). scipy 없이."""
    d = pd.concat([a.rename('a'), b.rename('b')], axis=1).dropna()
    return (d['a'].rank().corr(d['b'].rank()), len(d)) if len(d) > 10 else (np.nan, len(d))


def ccf(x, y, maxlag=12):
    """x 를 k개월 shift 했을 때 y 와의 상관. k<0 이면 x 가 y를 선행."""
    out = {}
    for k in range(-maxlag, maxlag + 1):
        r, n = sp(x.shift(k), y)
        if n >= 40:
            out[k] = r
    return out


# ── 후보 구성 ─────────────────────────────────────────────
cand = {}
if 'CPI' in df and 'PPI' in df:
    cpi = np.log(df['CPI']).diff(12) * 100
    ppi = np.log(df['PPI']).diff(12) * 100
    cand['채산성'] = (cpi - ppi).rename('채산성')
if 'JP10Y' in df:
    cand['일본10년'] = df['JP10Y']
if '원엔100' in df:
    cand['원/엔'] = df['원엔100']
if '원위안' in df:
    cand['원/위안'] = df['원위안']

for ix in ('KOSPI', 'KOSDAQ'):
    fwd = np.log(df[f'{ix}_종가']).diff(12).shift(-12)
    print('=' * 74)
    print(f'{ix}  -  후보 신호 판정 (12개월 선행수익 대상)')
    print('=' * 74)
    print(f'{"후보":10s} {"IC":>7s} {"n":>5s} {"판정":>12s}   CCF 최대상관 시점')
    for nm, s in cand.items():
        r, n = sp(s, fwd)
        c = ccf(s, fwd)
        if c:
            bk = max(c, key=lambda k: abs(c[k]))
            ctxt = f'lag {bk:+3d}개월  r={c[bk]:+.3f}'
        else:
            ctxt = '-'
        ok = (abs(r) >= 0.10) and (n >= 60)
        print(f'{nm:10s} {r:+7.3f} {n:5d} {"가중 후보" if ok else "REF_ONLY":>12s}   {ctxt}')

    # 기존 신호와의 중복도
    print(f'\n  기존 신호와의 최대 |상관| (0.7 넘으면 중복 우려)')
    ex = {}
    for item in bd.signals_for(ix):
        try:
            ex[item[0]] = pd.Series(item[1]).astype(float)
        except Exception:
            pass
    for nm, s in cand.items():
        best, bn = 0.0, ''
        for en, es in ex.items():
            r, n = sp(s, es)
            if n >= 60 and abs(r) > abs(best):
                best, bn = r, en
        print(f'    {nm:10s} 최대 {best:+.3f}  ({bn})')
    print()
