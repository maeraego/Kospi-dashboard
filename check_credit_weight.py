# -*- coding: utf-8 -*-
"""
check_credit_weight.py — 신용융자/고객예탁금을 메인 대시보드에 넣으면 가중이 얼마가 되나

가중치를 감으로 정하지 않는다. build_dashboard.py 의 기존 공식
  IC × Ridge ÷ (1 + 평균절대상관)
에 신호를 넣고 나오는 값을 그대로 읽는다. 그리고 표본외 IC가 실제로 개선되는지 본다.

신호: 신용융자 ÷ 투자자예탁금 (금융투자협회 FreeSIS 일별 → 월말)
  · T+1 공표라 일별에서 shift(1) 후 월말 추출 (월말 시점에 실제로 알 수 있는 값)
  · 방향 prior = -1 (레버리지 높을수록 약세)
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

df = m.df
NEW = '신용융자/예탁금'


def ez(s, mp=36):
    return (s - s.expanding(mp).mean()) / s.expanding(mp).std()


def credit_ratio():
    kf = pd.read_parquet('kofia_daily.parquet')
    r = (kf['신용융자'] / kf['투자자예탁금']).shift(1)     # T+1 공표
    return r.resample('ME').last()


def ridge_w(cols, tr, lams=(10, 30, 100)):
    X = tr[cols].values
    sd = X.std(0); sd[sd == 0] = 1
    Xs = (X - X.mean(0)) / sd
    yy = tr['_y'].values - tr['_y'].mean()
    G, b = Xs.T @ Xs, Xs.T @ yy
    Ws = []
    for lam in lams:
        beta = np.linalg.solve(G + lam * np.eye(len(cols)), b)
        aa = np.abs(beta)
        if aa.sum() > 0:
            Ws.append(aa / aa.sum())
    return pd.Series(np.mean(Ws, axis=0), index=cols)


def full_weights(Z, IC, keep, y):
    """build_dashboard.analyze() 의 가중 공식을 그대로 재현."""
    D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
    rw = ridge_w(keep, D)
    w = pd.Series({c: IC[c] * float(rw[c]) for c in keep})
    CC = Z[keep].corr().abs()
    for c in keep:
        ac = (CC[c].sum() - 1) / (len(keep) - 1) if len(keep) > 1 else 0.0
        w[c] = w[c] / (1 + 1.0 * ac)
    return w / w.sum()


def build(ix, with_new):
    P = df[f'{ix}_종가']
    y = np.log(P.shift(-12) / P)
    sig = list(m.signals_for(ix))
    if with_new:
        sig.append((NEW, credit_ratio().reindex(df.index), -1, None, None))
    Z, IC, NOBS = {}, {}, {}
    for t in sig:
        n, s_, base = t[0], t[1], t[2]
        if s_ is None:
            continue
        xx = pd.concat([ez(s_) * base, y], axis=1, sort=True).dropna()
        r = xx.iloc[:, 0].corr(xx.iloc[:, 1]) if len(xx) > 40 else 0.0
        if n in ('한국VIX', 'VIX 급등(YoY)'):
            eff = abs(base)
        else:
            eff = base if r >= 0 else -base
        Z[n] = ez(s_) * eff
        IC[n] = abs(float(r))
        NOBS[n] = len(xx)
    Z = pd.DataFrame(Z).ffill(limit=3)
    REF = {'시가총액/M2', 'M2/M1 비율', '수출 YoY', 'M2 증가율(YoY)'}
    keep = [c for c in Z.columns if IC[c] >= 0.10 and NOBS.get(c, 0) >= 60 and c not in REF]
    return Z, IC, NOBS, keep, y


def oos(ix, with_new, split='2015'):
    Z, IC, NOBS, keep, y = build(ix, with_new)
    D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
    tr, te = D[D.index <= split], D[D.index > split]
    if len(tr) < 40 or len(te) < 20:
        return None
    rw = ridge_w(keep, tr)
    w = pd.Series({c: IC[c] * rw[c] for c in keep})
    CC = tr[keep].corr().abs()
    for c in keep:
        ac = (CC[c].sum() - 1) / (len(keep) - 1) if len(keep) > 1 else 0.0
        w[c] = w[c] / (1 + ac)
    w = w / w.sum()
    return float((te[keep] * w).sum(axis=1).corr(te['_y']))


for ix in ('KOSPI', 'KOSDAQ'):
    print("=" * 74)
    print(f"  {ix}")
    print("=" * 74)
    Z, IC, NOBS, keep, y = build(ix, True)
    if NEW not in keep:
        print(f"  [탈락] {NEW}  IC={IC.get(NEW, 0):.3f}  n={NOBS.get(NEW, 0)}  "
              f"(IC_MIN 0.10 / MIN_OBS 60 미달)")
    w = full_weights(Z, IC, keep, y)

    print(f"\n  ① 단독 IC (expanding z vs 향후 12개월 로그수익)")
    print(f"     {NEW}: IC = {IC.get(NEW, float('nan')):.3f}   표본 {NOBS.get(NEW, 0)}개월")

    print(f"\n  ② 기존 신호와의 상관 (절대값 상위 5)")
    if NEW in Z:
        cc = Z[keep].corr()[NEW].abs().drop(NEW, errors='ignore').sort_values(ascending=False)
        for n, v in cc.head(5).items():
            flag = '  ← 중복 우려' if v > 0.7 else ''
            print(f"     {n:18s} {v:.3f}{flag}")
        print(f"     평균절대상관 = {cc.mean():.3f}")

    print(f"\n  ③ 공식이 내놓는 가중치 (IC×Ridge÷(1+평균상관), 전 표본)")
    for n in w.sort_values(ascending=False).index:
        mark = '  ★' if n == NEW else ''
        print(f"     {n:18s} {w[n]*100:5.2f}%   (단독IC {IC[n]:.3f}){mark}")

    a, b = oos(ix, False), oos(ix, True)
    print(f"\n  ④ 표본외 IC (2015년 이전 학습 → 이후 검증)")
    print(f"     기존        {a:+.4f}" if a is not None else "     기존        —")
    print(f"     +신용융자   {b:+.4f}" if b is not None else "     +신용융자   —")
    if a is not None and b is not None:
        d = b - a
        print(f"     차이        {d:+.4f}  {'개선' if d > 0 else '악화' if d < 0 else '동일'}")
    print()
