# -*- coding: utf-8 -*-
"""
check_anchor.py — 예측 앵커(장기추세) 자체를 고치는 실험

[문제] 현행 앵커는 log(현재가/100) / 경과연수 다. 이 정의는 현재가를 그대로
  통과시켜 '추세 대비 괴리'가 구조적으로 항상 0이 된다. 그래서 지수가 높을수록
  앵커가 커지고, 실측에서 앵커와 이후 12개월 수익의 상관이 -0.532로 나온다.
  비쌀 때 더 오른다고 말하는 셈이라, 고평가 구간 과대예측(3/7에서 76%)의 뿌리다.

[대안] 기울기를 현재가에서 떼어낸다.
  A1  과거 로그가격에 OLS 추세선을 적합 → 기울기 b (현재가와 무관)
  A2  A1 + 평균회귀: 앵커 = b − λ·(추세선 대비 괴리)
      괴리가 양수(추세 위=비쌈)면 앵커를 낮춘다.

모든 적합은 시점 t까지의 가격만 쓴다(가격은 t시점에 이미 알려진 값이라
결과 수익과 달리 12개월 지연이 필요 없다).
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
LAMBDAS = [0.0, 0.10, 0.20, 0.30, 0.50]


def prem_for(tr_s, tr_y, s_now, shrink, tail=None, cap=None):
    o = np.argsort(tr_s)
    ys = np.asarray(tr_y)[o]
    n = len(ys)
    win = max(int(n * 0.20), 8)
    means = [float(ys[max(0, int((b + .5) / NB * n) - win // 2):
                      min(n, int((b + .5) / NB * n) + win // 2)].mean())
             for b in range(NB)]
    bar = sum(means) / NB
    b_now = int(np.clip(int((tr_s < s_now).mean() * NB), 0, NB - 1))
    k = tail if (tail is not None and b_now == NB - 1) else shrink
    p = (means[b_now] - bar) * k
    if cap is not None:
        p = float(np.clip(p, -cap, cap))
    return p, b_now


def run(idx='KOSPI', shrink=1.0, tail=None, cap=None):
    a = bd.analyze(idx)
    sc = a['sc']
    P = bd.df[f'{idx}_종가'].reindex(sc.index)
    y12 = np.log(P.shift(-12) / P)
    base_val, base_dt = ((100.0, pd.Timestamp('1980-01-04')) if idx == 'KOSPI'
                         else (1000.0, pd.Timestamp('1996-07-01')))
    s, y, dates = sc.values, y12.values, sc.index
    tyr = np.array([max((d - base_dt).days / 365.25, 1e-6) for d in dates])
    lp = np.log(P.values)

    rows = []
    for i in range(len(s)):
        je = i - 12
        if je < MIN_TRAIN or not np.isfinite(s[i]) or not np.isfinite(y[i]):
            continue
        m = np.isfinite(s[:je + 1]) & np.isfinite(y[:je + 1])
        tr_s, tr_y = s[:je + 1][m], y[:je + 1][m]
        if len(tr_s) < MIN_TRAIN:
            continue

        # 현행 앵커
        a0 = float(lp[i] - np.log(base_val)) / tyr[i]

        # 추세선: t시점까지의 로그가격에 OLS (가격은 이미 알려진 값)
        ok = np.isfinite(lp[:i + 1])
        b_sl, b_ic = np.polyfit(tyr[:i + 1][ok], lp[:i + 1][ok], 1)
        dev = float(lp[i] - (b_ic + b_sl * tyr[i]))     # 추세 대비 괴리(+면 비쌈)

        p, b_now = prem_for(tr_s, tr_y, s[i], shrink, tail, cap)
        rec = dict(date=dates[i], bin=b_now, realized=y[i], px=P.iloc[i],
                   dev=dev, A0=a0 + p, slope=b_sl)
        for lam in LAMBDAS:
            rec[f'A2_{lam}'] = (b_sl - lam * dev) + p
        rows.append(rec)
    return pd.DataFrame(rows).set_index('date')


def report(R, idx, shrink_label):
    r = R['realized']
    cols = [('A0', '현행 log(P/100)/연수')] + \
           [(f'A2_{l}', f'추세기울기 − {l:.2f}×괴리' if l else '추세기울기만 (λ=0)')
            for l in LAMBDAS]
    print("=" * 86)
    print(f"  {idx} 앵커 비교  ({shrink_label}, 평가 {len(R)}개월)")
    print("=" * 86)
    print(f"\n  {'앵커':<26s} {'RMSE':>7s} {'지수오차':>8s} {'보정기울기':>9s} "
          f"|| {'3/7 오차':>9s} {'7/7 오차':>9s}")
    b3, b7 = R['bin'] == 2, R['bin'] == NB - 1
    for k, lab in cols:
        e = R[k] - r
        slope = float(np.polyfit(R[k], r, 1)[0])
        print(f"  {lab:<26s} {np.sqrt((e**2).mean()):>7.4f} "
              f"{(np.exp(e.abs())-1).mean()*100:>7.2f}% {slope:>9.2f} "
              f"|| {e[b3].mean():>+9.4f} {e[b7].mean():>+9.4f}")
    print(f"\n  [읽는 법] 3/7·7/7 오차는 예측−실제(로그). 양수=과대. 0에 가까울수록 좋다.")
    print(f"            현행은 3/7 과대(+)·7/7 과소(−)가 동시에 큰 게 문제였다.")


if __name__ == '__main__':
    for ix in ('KOSPI', 'KOSDAQ'):
        report(run(ix, shrink=1.0), ix, '축소 1.0 전체')
        print()
