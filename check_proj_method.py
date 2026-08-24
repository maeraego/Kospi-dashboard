# -*- coding: utf-8 -*-
"""
check_proj_method.py — 예측 중앙값 산출 방식 비교 (워크포워드 백테스트)

질문: "구간 조회(현행) vs 회귀, 뭐가 더 신뢰도 높나?"

[중요] 기준선을 반드시 함께 본다. 점수를 아예 무시하고 장기 CAGR만 쓰는 예측이
       기준선이다. 두 방식이 이걸 못 이기면 "어느 쪽이 나은가"는 의미가 없다.

비교 대상
  C) CAGR만          점수 무시. 현재가 × exp(장기CAGR)          ← 기준선
  A) 구간조회(현행)   CAGR + (구간평균 − 구간평균들의평균) × 0.5
  B) 회귀(순수)       OLS: y12 = a + b·score
  D) 회귀(CAGR앵커)   CAGR + b·(score − 학습평균score)
  E) 회귀(앵커+0.5)   CAGR + b·(score − 학습평균score) × 0.5

[룩어헤드 차단] 시점 t에서 학습에 쓰는 표본은 12개월 뒤 수익이 이미 실현된 것,
  즉 j + 12 <= t 인 j 뿐이다. t 시점에 아직 결과를 모르는 표본은 안 쓴다.

[한계] 점수(sc) 자체는 build_dashboard가 전체표본 IC·가중으로 만든다. 즉 점수에는
  룩어헤드가 남아 있어 모든 방식의 절대 정확도가 낙관적으로 나온다. 다만 모든
  방식이 같은 점수를 쓰므로 '방식 간 비교'는 공정하다.
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
SHRINK = 0.5
MIN_TRAIN = 120          # 학습 최소 10년


def bin_pred(tr_s, tr_y, s_now, cagr, shrink=SHRINK):
    """현행 방식: 겹침 이동창으로 구간평균 → 프리미엄 절반만 CAGR에 더한다."""
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
    return cagr + (means[b_now] - bar) * shrink


def fit_slope(tr_s, tr_y):
    b, a = np.polyfit(tr_s, tr_y, 1)
    return float(b), float(a)


def backtest(idx='KOSPI'):
    a = bd.analyze(idx)
    sc = a['sc']
    P = bd.df[f'{idx}_종가'].reindex(sc.index)
    y12 = np.log(P.shift(-12) / P)

    base_val, base_dt = ((100.0, pd.Timestamp('1980-01-04')) if idx == 'KOSPI'
                         else (1000.0, pd.Timestamp('1996-07-01')))

    s = sc.values
    y = y12.values
    dates = sc.index
    rows = []

    for i in range(len(s)):
        if not np.isfinite(y[i]):
            continue                       # 실현값이 없으면 평가 불가
        j_end = i - 12                     # 여기까지만 결과를 알 수 있다
        if j_end < MIN_TRAIN:
            continue
        m = np.isfinite(s[:j_end + 1]) & np.isfinite(y[:j_end + 1])
        tr_s, tr_y = s[:j_end + 1][m], y[:j_end + 1][m]
        if len(tr_s) < MIN_TRAIN or not np.isfinite(s[i]) or not np.isfinite(P.iloc[i]):
            continue

        yrs = max((dates[i] - base_dt).days / 365.25, 1)
        cagr = float(np.log(P.iloc[i] / base_val) / yrs)

        b, a0 = fit_slope(tr_s, tr_y)
        dev = s[i] - tr_s.mean()

        rows.append(dict(
            date=dates[i], realized=y[i],
            C_cagr=cagr,
            A_bin=bin_pred(tr_s, tr_y, s[i], cagr),
            B_reg=a0 + b * s[i],
            D_reg_anchor=cagr + b * dev,
            E_reg_anchor_half=cagr + b * dev * SHRINK,
        ))

    return pd.DataFrame(rows).set_index('date')


def report(R, idx):
    methods = [('C_cagr', 'C) CAGR만 (기준선)'),
               ('A_bin', 'A) 구간조회 (현행)'),
               ('B_reg', 'B) 회귀 (순수)'),
               ('D_reg_anchor', 'D) 회귀 (CAGR앵커)'),
               ('E_reg_anchor_half', 'E) 회귀 (앵커+0.5)')]
    r = R['realized']
    eff = len(R) / 12.0

    print("=" * 84)
    print(f"  {idx} 예측방식 워크포워드 비교")
    print(f"  평가 {len(R)}개월 ({R.index[0]:%Y-%m} ~ {R.index[-1]:%Y-%m}) · "
          f"중첩 보정 유효표본 ~{eff:.0f}개")
    print("=" * 84)
    print(f"\n  {'방식':<20s} {'RMSE':>7s} {'MAE':>7s} {'편향':>8s} "
          f"{'상관':>7s} {'방향적중':>8s} {'보정기울기':>10s}")
    best = {}
    for k, lab in methods:
        e = R[k] - r
        rmse, mae, bias = float(np.sqrt((e ** 2).mean())), float(e.abs().mean()), float(e.mean())
        corr = float(R[k].corr(r))
        hit = float((np.sign(R[k]) == np.sign(r)).mean())
        # 보정: 실현값을 예측값에 회귀. 1.0이면 예측 강도가 딱 맞다.
        slope = float(np.polyfit(R[k], r, 1)[0])
        best[k] = rmse
        print(f"  {lab:<20s} {rmse:>7.4f} {mae:>7.4f} {bias:>+8.4f} "
              f"{corr:>7.3f} {hit*100:>7.1f}% {slope:>10.2f}")

    win = min(best, key=best.get)
    print(f"\n  RMSE 최소: {dict(methods)[win]}")
    print(f"  기준선(CAGR만) 대비 개선폭")
    for k, lab in methods:
        if k == 'C_cagr':
            continue
        d = best['C_cagr'] - best[k]
        print(f"    {lab:<20s} {d:+.4f}  {'개선' if d > 0 else '악화'}")

    # 지수 수준으로도 본다 — 사용자가 실제로 보는 숫자
    print(f"\n  같은 결과를 지수 수준 오차로 (평균 절대 오차율)")
    for k, lab in methods:
        print(f"    {lab:<20s} {(np.exp((R[k]-r).abs())-1).mean()*100:>6.2f}%")

    # 회귀 기울기가 시간에 따라 안정적인가 — 신뢰도의 핵심
    print(f"\n  [신뢰도] 예측-실현 상관을 전후반으로 쪼개면")
    half = len(R) // 2
    print(f"    {'방식':<20s} {'전반':>8s} {'후반':>8s} {'차이':>8s}")
    for k, lab in methods:
        if k == 'C_cagr':
            continue
        c1 = float(R[k].iloc[:half].corr(r.iloc[:half]))
        c2 = float(R[k].iloc[half:].corr(r.iloc[half:]))
        print(f"    {lab:<20s} {c1:>8.3f} {c2:>8.3f} {c2-c1:>+8.3f}")


def block_bootstrap(R, k1, k2, n_boot=4000, block=12, seed=0):
    """12개월 중첩 표본이라 단순 부트스트랩은 못 쓴다. 12개월 블록으로 재표집해
    RMSE 차이(k1 - k2)의 분포를 구한다. 0을 포함하면 '차이 없음'."""
    rng = np.random.default_rng(seed)
    r = R['realized'].values
    e1 = (R[k1].values - r) ** 2
    e2 = (R[k2].values - r) ** 2
    n = len(r)
    nb = max(n // block, 1)
    diffs = []
    for _ in range(n_boot):
        st = rng.integers(0, max(n - block, 1), size=nb)
        pick = np.concatenate([np.arange(t, min(t + block, n)) for t in st])
        diffs.append(np.sqrt(e1[pick].mean()) - np.sqrt(e2[pick].mean()))
    d = np.array(diffs)
    return float(d.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)), float((d > 0).mean())


def significance(R, idx):
    print(f"\n  [유의성] 현행(A) vs 회귀 — 12개월 블록 부트스트랩 4,000회")
    print(f"    RMSE 차이 = A(현행) - 회귀.  음수면 현행이 낫다.")
    print(f"    {'비교':<24s} {'평균차':>9s} {'95% 구간':>20s} {'판정':>12s}")
    for k2, lab in (('B_reg', 'A vs B 회귀(순수)'),
                    ('D_reg_anchor', 'A vs D 회귀(CAGR앵커)')):
        m, lo, hi, pgt = block_bootstrap(R, 'A_bin', k2)
        verdict = '차이 없음' if lo <= 0 <= hi else ('회귀 우세' if m > 0 else '현행 우세')
        print(f"    {lab:<24s} {m:>+9.4f}  [{lo:+.4f}, {hi:+.4f}] {verdict:>12s}")


if __name__ == '__main__':
    for ix in ('KOSPI', 'KOSDAQ'):
        R = backtest(ix)
        report(R, ix)
        significance(R, ix)
        print()


def shrink_sweep(idx='KOSPI'):
    """축소계수 0.5가 최적인가. 보정기울기 1.0이 '강도가 딱 맞다'는 뜻이다."""
    a = bd.analyze(idx)
    sc = a['sc']
    P = bd.df[f'{idx}_종가'].reindex(sc.index)
    y12 = np.log(P.shift(-12) / P)
    base_val, base_dt = ((100.0, pd.Timestamp('1980-01-04')) if idx == 'KOSPI'
                         else (1000.0, pd.Timestamp('1996-07-01')))
    s, y, dates = sc.values, y12.values, sc.index

    shrinks = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
    preds = {k: [] for k in shrinks}
    real = []
    for i in range(len(s)):
        if not np.isfinite(y[i]):
            continue
        j_end = i - 12
        if j_end < MIN_TRAIN:
            continue
        m = np.isfinite(s[:j_end + 1]) & np.isfinite(y[:j_end + 1])
        tr_s, tr_y = s[:j_end + 1][m], y[:j_end + 1][m]
        if len(tr_s) < MIN_TRAIN or not np.isfinite(s[i]):
            continue
        cagr = float(np.log(P.iloc[i] / base_val) /
                     max((dates[i] - base_dt).days / 365.25, 1))
        for k in shrinks:
            preds[k].append(bin_pred(tr_s, tr_y, s[i], cagr, shrink=k))
        real.append(y[i])

    real = np.array(real)
    print(f"\n  [축소계수 스윕] {idx} — 현행은 0.5")
    print(f"    {'축소':>5s} {'RMSE':>8s} {'MAE':>8s} {'보정기울기':>10s} {'지수오차':>9s}")
    for k in shrinks:
        p = np.array(preds[k])
        e = p - real
        slope = float(np.polyfit(p, real, 1)[0]) if p.std() > 1e-9 else float('nan')
        mark = '  <- 현행' if k == 0.5 else ''
        print(f"    {k:>5.2f} {np.sqrt((e**2).mean()):>8.4f} {np.abs(e).mean():>8.4f} "
              f"{slope:>10.2f} {(np.exp(np.abs(e))-1).mean()*100:>8.2f}%{mark}")
