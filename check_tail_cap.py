# -*- coding: utf-8 -*-
"""
check_tail_cap.py — 축소계수를 올리되 극단 구간(7/7)만 억제하는 절충안 시험

배경: check_proj_method.py 결과, 축소 0.5는 예측 강도를 2.3배 눌러
  (보정기울기 2.34) 평시 정확도를 깎고 있었다. 1.0이 RMSE·보정 모두 최적.
  그런데 0.5를 쓴 원래 이유는 "유리 국면은 대개 폭락 직후 바닥이라 그때
  반등률(+40~200%)을 지금 고점에 붙이면 과대추정"이었다.

  → 평시는 축소를 풀고, 극단 구간만 눌러두는 절충이 가능한가?

[한계 — 먼저 읽을 것] 평가구간에서 7/7 진입은 KOSPI 19개월뿐이고,
  12개월 중첩이라 유효표본은 ~1.6개다. 즉 이 시험은 꼬리 성능을
  '통계적으로 판정'하지 못한다. 할 수 있는 건 그 몇 안 되는 에피소드에서
  각 안이 실제로 얼마나 빗나갔는지 눈으로 보는 것뿐이다.
"""
import numpy as np
import pandas as pd

import check_proj_method as M

bd = M.bd
NB, MIN_TRAIN = M.NB, M.MIN_TRAIN


def bin_pred2(tr_s, tr_y, s_now, cagr, shrink, tail_shrink=None, cap=None):
    """구간조회 + (극단구간 전용 축소) + (프리미엄 절대 상한)."""
    o = np.argsort(tr_s)
    ys = np.asarray(tr_y)[o]
    n = len(ys)
    win = max(int(n * 0.20), 8)
    means = []
    for b in range(NB):
        c = int((b + 0.5) / NB * n)
        means.append(float(ys[max(0, c - win // 2):min(n, c + win // 2)].mean()))
    bar = sum(means) / NB
    b_now = int(np.clip(int((tr_s < s_now).mean() * NB), 0, NB - 1))

    k = shrink
    if tail_shrink is not None and b_now in (0, NB - 1):   # 양 끝 구간
        k = tail_shrink
    prem = (means[b_now] - bar) * k
    if cap is not None:
        prem = float(np.clip(prem, -cap, cap))
    return cagr + prem, b_now


VARIANTS = [
    ('현행 0.50',            dict(shrink=0.50)),
    ('0.75 전체',            dict(shrink=0.75)),
    ('1.00 전체',            dict(shrink=1.00)),
    ('1.00 / 극단 0.50',     dict(shrink=1.00, tail_shrink=0.50)),
    ('1.00 / 극단 0.25',     dict(shrink=1.00, tail_shrink=0.25)),
    ('0.75 / 극단 0.50',     dict(shrink=0.75, tail_shrink=0.50)),
    ('1.00 + 상한 0.15',     dict(shrink=1.00, cap=0.15)),
    ('1.00 + 상한 0.20',     dict(shrink=1.00, cap=0.20)),
]


def run(idx='KOSPI'):
    a = bd.analyze(idx)
    sc = a['sc']
    P = bd.df[f'{idx}_종가'].reindex(sc.index)
    y12 = np.log(P.shift(-12) / P)
    base_val, base_dt = ((100.0, pd.Timestamp('1980-01-04')) if idx == 'KOSPI'
                         else (1000.0, pd.Timestamp('1996-07-01')))
    s, y, dates = sc.values, y12.values, sc.index

    recs = {lab: [] for lab, _ in VARIANTS}
    meta = []
    for i in range(len(s)):
        if not np.isfinite(y[i]):
            continue
        je = i - 12
        if je < MIN_TRAIN:
            continue
        m = np.isfinite(s[:je + 1]) & np.isfinite(y[:je + 1])
        tr_s, tr_y = s[:je + 1][m], y[:je + 1][m]
        if len(tr_s) < MIN_TRAIN or not np.isfinite(s[i]):
            continue
        cagr = float(np.log(P.iloc[i] / base_val) /
                     max((dates[i] - base_dt).days / 365.25, 1))
        b_now = None
        for lab, kw in VARIANTS:
            p, b_now = bin_pred2(tr_s, tr_y, s[i], cagr, **kw)
            recs[lab].append(p)
        meta.append((dates[i], y[i], b_now, P.iloc[i]))

    md = pd.DataFrame(meta, columns=['date', 'realized', 'bin', 'px']).set_index('date')
    R = pd.DataFrame(recs, index=md.index)
    return R, md


def report(R, md, idx):
    r = md['realized']
    tail = md['bin'] == NB - 1
    print("=" * 88)
    print(f"  {idx} — 극단구간 상한 절충안  (평가 {len(md)}개월, "
          f"7/7 진입 {int(tail.sum())}개월 = 유효 ~{tail.sum()/12:.1f}개)")
    print("=" * 88)

    print(f"\n  {'안':<18s} {'RMSE':>7s} {'지수오차':>8s} {'보정기울기':>10s} "
          f"|| {'7/7 RMSE':>9s} {'7/7 평균오차':>11s} {'7/7 최대과대':>11s}")
    for lab, _ in VARIANTS:
        p = R[lab]
        e = p - r
        slope = float(np.polyfit(p, r, 1)[0])
        et = e[tail]
        mark = '  <- 현행' if lab.startswith('현행') else ''
        print(f"  {lab:<18s} {np.sqrt((e**2).mean()):>7.4f} "
              f"{(np.exp(e.abs())-1).mean()*100:>7.2f}% {slope:>10.2f} "
              f"|| {np.sqrt((et**2).mean()):>9.4f} {et.mean():>+11.4f} "
              f"{et.max():>+11.4f}{mark}")

    print(f"\n  [해석] 7/7 평균오차가 양수 = 과대예측. 최대과대는 최악의 한 달.")

    if tail.sum():
        print(f"\n  7/7 진입 시기 (연속 구간)")
        d = md[tail].index
        runs, st = [], d[0]
        for k in range(1, len(d)):
            if (d[k].to_period('M') - d[k-1].to_period('M')).n > 1:
                runs.append((st, d[k-1])); st = d[k]
        runs.append((st, d[-1]))
        for s_, e_ in runs:
            seg = md[(md.index >= s_) & (md.index <= e_)]
            print(f"    {s_:%Y-%m} ~ {e_:%Y-%m} ({len(seg)}개월) "
                  f"실현 12개월수익 평균 {np.exp(seg['realized'].mean())-1:+.1%}")

        print(f"\n  그 시기 예측 vs 실현 (지수 수준, 대표 3개월)")
        pick = md[tail].index[::max(len(d)//3, 1)][:3]
        print(f"    {'시점':<9s} {'현재가':>8s} {'실현':>8s} "
              + ' '.join(f'{lab[:11]:>12s}' for lab, _ in VARIANTS[:4]))
        for t in pick:
            px = md.loc[t, 'px']
            act = px * np.exp(md.loc[t, 'realized'])
            cells = ' '.join(f"{px*np.exp(R.loc[t, lab]):>12,.0f}" for lab, _ in VARIANTS[:4])
            print(f"    {t:%Y-%m}   {px:>8,.0f} {act:>8,.0f} {cells}")


if __name__ == '__main__':
    for ix in ('KOSPI', 'KOSDAQ'):
        R, md = run(ix)
        report(R, md, ix)
        print()
