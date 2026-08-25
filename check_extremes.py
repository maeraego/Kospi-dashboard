# -*- coding: utf-8 -*-
"""
check_extremes.py — 두 가지 질문에 답한다

1. 현재 코스피가 극단 국면이라면 예측이 얼마가 되나?
   (역사적 프리미엄 최대·최소를 지금 지수에 적용)
2. 과거 고평가·저평가 구간에서 1년 뒤 예측값 대비 실제값은 어땠나?

예측 로직은 build_dashboard.py의 현재 설정을 그대로 재현한다
  코스피: 축소 1.0, 최상위 구간만 0.5
  코스닥: 축소 1.0 + 프리미엄 상한 ±0.20
"""
import io
import contextlib
import importlib.util
import sys
import os
import numpy as np
import pandas as pd

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
bd = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(bd)

NB = 7
MIN_TRAIN = 120


def cfg(idx):
    """build_dashboard와 동일한 축소 설정."""
    return (1.0, 0.5, None) if idx == 'KOSPI' else (1.0, None, 0.20)


def mono(vals):
    """build_dashboard._mono 와 같은 PAVA (표본수 동일 가정)."""
    v = list(vals)
    i = 0
    while i < len(v) - 1:
        if v[i] > v[i + 1]:
            nv = (v[i] + v[i + 1]) / 2
            v[i] = v[i + 1] = nv
            if i > 0:
                i -= 1
        else:
            i += 1
    return v


def bin_centers(tr_s, tr_y, cagr, idx):
    """7개 구간 각각의 center(로그 기대수익)와 구간 프리미엄."""
    shrink, tail, cap = cfg(idx)
    o = np.argsort(tr_s)
    ys = np.asarray(tr_y)[o]
    n = len(ys)
    win = max(int(n * 0.20), 8)
    means = []
    for b in range(NB):
        c = int((b + 0.5) / NB * n)
        means.append(float(ys[max(0, c - win // 2):min(n, c + win // 2)].mean()))
    bar = sum(means) / NB
    prems = []
    for b in range(NB):
        k = tail if (tail is not None and b == NB - 1) else shrink
        p = (means[b] - bar) * k
        if cap is not None:
            p = float(np.clip(p, -cap, cap))
        prems.append(p)
    centers = mono([cagr + p for p in prems])
    return centers, prems


def series(idx):
    a = bd.analyze(idx)
    sc = a['sc']
    P = bd.df[f'{idx}_종가'].reindex(sc.index)
    y12 = np.log(P.shift(-12) / P)
    base_val, base_dt = ((100.0, pd.Timestamp('1980-01-04')) if idx == 'KOSPI'
                         else (1000.0, pd.Timestamp('1996-07-01')))
    return a, sc, P, y12, base_val, base_dt


def walk(idx):
    """워크포워드: 각 시점의 예측 center, 배정 구간, 프리미엄, 실현값."""
    a, sc, P, y12, base_val, base_dt = series(idx)
    s, y, dates = sc.values, y12.values, sc.index
    rows = []
    for i in range(len(s)):
        je = i - 12
        if je < MIN_TRAIN or not np.isfinite(s[i]):
            continue
        m = np.isfinite(s[:je + 1]) & np.isfinite(y[:je + 1])
        tr_s, tr_y = s[:je + 1][m], y[:je + 1][m]
        if len(tr_s) < MIN_TRAIN:
            continue
        cagr = float(np.log(P.iloc[i] / base_val) /
                     max((dates[i] - base_dt).days / 365.25, 1))
        centers, prems = bin_centers(tr_s, tr_y, cagr, idx)
        b = int(np.clip(int((tr_s < s[i]).mean() * NB), 0, NB - 1))
        rows.append(dict(date=dates[i], px=P.iloc[i], bin=b, score=s[i],
                         cagr=cagr, prem=prems[b], center=centers[b],
                         pred=P.iloc[i] * np.exp(centers[b]),
                         realized=y[i],
                         actual=P.iloc[i] * np.exp(y[i]) if np.isfinite(y[i]) else np.nan))
    return pd.DataFrame(rows).set_index('date')


# ══════════════════════════════════════════════════════════
def q1_extremes(idx='KOSPI'):
    a, sc, P, y12, base_val, base_dt = series(idx)
    W = walk(idx)
    px = float(P.dropna().iloc[-1])
    cur_bin = a['cbin']
    pj = a['proj']

    print("=" * 78)
    print(f"  ① {idx} 현재 {px:,.0f} — 극단 프리미엄을 적용하면")
    print("=" * 78)

    # (a) 지금 표본으로 만든 7구간
    pb = a['tbl']['projbins']
    ks = sorted(pb, key=lambda k: int(k))
    print(f"\n  [a] 지금 데이터의 7구간 사다리  (현재는 {cur_bin+1}/7 = {pj['med']:,.0f})")
    for k in ks:
        m = pb[k]['med']
        mark = '  <- 지금' if int(k) == cur_bin else ''
        print(f"      {int(k)+1}/7   {m:>8,.0f}   ({m/px-1:+6.1%}){mark}")

    # (b) 역사적으로 이 모델이 매긴 프리미엄의 최대·최소
    print(f"\n  [b] 역사적 프리미엄 극단  (워크포워드 {len(W)}개월 동안 모델이 실제로 매긴 값)")
    pmax, pmin = W['prem'].max(), W['prem'].min()
    dmax, dmin = W['prem'].idxmax(), W['prem'].idxmin()
    for lab, p, d in (('최대', pmax, dmax), ('최소', pmin, dmin)):
        cagr_now = float(np.log(px / base_val) /
                         max((P.dropna().index[-1] - base_dt).days / 365.25, 1))
        v = px * np.exp(cagr_now + p)
        print(f"      {lab} 프리미엄 {p:+.4f} ({d:%Y-%m}, 당시 {W.loc[d,'bin']+1}/7)"
              f"  → 지금 적용 시 {v:>8,.0f}  ({v/px-1:+.1%})")

    # (c) 실제로 일어났던 12개월 수익의 극단
    print(f"\n  [c] 참고 — 실제로 일어난 12개월 수익의 극단 (1995~)")
    yy = y12.dropna()
    for lab, f in (('최대', yy.idxmax()), ('최소', yy.idxmin())):
        v = px * np.exp(yy[f])
        print(f"      {lab} {np.exp(yy[f])-1:+7.1%} ({f:%Y-%m} 진입)"
              f"  → 지금 적용 시 {v:>8,.0f}")
    print(f"\n      모델의 극단({pmin:+.3f}~{pmax:+.3f})은 실제 극단"
          f"({yy.min():+.3f}~{yy.max():+.3f})보다 훨씬 좁다.")
    print(f"      장기 CAGR 앵커에 묶여 있어서, 예측은 폭락·폭등을 구조적으로 못 낸다.")


# ══════════════════════════════════════════════════════════
def q2_by_regime(idx='KOSPI'):
    W = walk(idx).dropna(subset=['realized'])
    print("\n" + "=" * 78)
    print(f"  ② {idx} 과거 구간별 — 1년 뒤 예측 vs 실제  (평가 {len(W)}개월)")
    print("=" * 78)
    print(f"\n  {'구간':<7s} {'개월':>4s} {'평균예측':>9s} {'평균실제':>9s} "
          f"{'오차':>9s} {'예측>실제':>9s} {'평균 지수오차':>12s}")
    for b in range(NB):
        g = W[W['bin'] == b]
        if not len(g):
            print(f"  {b+1}/7    {0:>4d}      (진입 없음)")
            continue
        pr = np.exp(g['center']) - 1
        ac = np.exp(g['realized']) - 1
        err = g['center'] - g['realized']
        over = (err > 0).mean()
        print(f"  {b+1}/7  {len(g):>6d} {pr.mean():>+9.1%} {ac.mean():>+9.1%} "
              f"{err.mean():>+9.4f} {over:>8.0%} {(np.exp(err.abs())-1).mean():>11.1%}")
    print(f"\n  [읽는 법] 오차 = 예측 − 실제 (로그). 양수면 과대예측.")
    print(f"            1/7 = 가장 불리(고평가), 7/7 = 가장 유리(저평가)")


if __name__ == '__main__':
    q1_extremes('KOSPI')
    q2_by_regime('KOSPI')
