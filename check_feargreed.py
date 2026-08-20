# -*- coding: utf-8 -*-
"""
check_feargreed.py — 공포탐욕지수를 코스피 대시보드에 넣을 만한지 검증

세 가지를 본다.
  ① 투자 성과 : 공포탐욕 구간별 이후 12개월 수익·승률 ("이걸로 투자했다면")
  ② CCF      : 코스피를 선행하나 후행하나 (flow_ccf.py의 사전백색화+에코가드 재사용)
  ③ 편입 가치 : 대시보드 공식 IC×Ridge÷(1+평균상관)이 내놓는 가중과 표본외 IC 개선

공포탐욕은 이미 대시보드에 있는 VKOSPI·신용융자/예탁금·신용스프레드를 재료로 쓴다.
따라서 핵심 질문은 "예측력이 있나"가 아니라 "기존 신호와 겹치지 않나"이다.
(VKOSPI vs 실현변동성에서 배운 교훈 — 상관 0.89짜리를 둘 다 넣으면 공포를 두 번 센다)
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
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m)
df = m.df

import flow_ccf as fc

FG = pd.read_parquet('fear_greed_daily.parquet')
KR, US = 'KR_공포탐욕', 'US_공포탐욕'
FORCED = ('실현변동성(20일)', 'VKOSPI', 'VIX 급등(YoY)')
REF = {'시가총액/M2', 'M2/M1 비율', '수출 YoY', 'M2 증가율(YoY)'}


def ez(s, mp=36):
    return (s - s.expanding(mp).mean()) / s.expanding(mp).std()


def monthly(col):
    return FG[col].resample('ME').last()


def kospi():
    px = pd.read_parquet('krx_daily.parquet')['KOSPI_종가'].dropna()
    px.index = pd.to_datetime(px.index)
    return px


# ══════════════════════════════════════════════════════════
# ① 투자 성과
# ══════════════════════════════════════════════════════════
def perf(col, label):
    px = kospi()
    fwd = np.log(px.shift(-252) / px)
    d = pd.concat([FG[col].rename('fg'), fwd.rename('r')], axis=1).dropna()

    bins = [(0, 25, '극단적 공포'), (25, 45, '공포'), (45, 55, '중립'),
            (55, 75, '탐욕'), (75, 101, '극단적 탐욕')]
    print(f"\n  [{label}] 진입 시점 구간별, 이후 12개월  (표본 {len(d):,}일·중첩)")
    print(f"    {'구간':<12s} {'일수':>7s} {'평균':>9s} {'중앙값':>9s} {'승률':>7s}")
    for lo, hi, name in bins:
        g = d[(d.fg >= lo) & (d.fg < hi)]
        if len(g) < 60:
            print(f"    {name:<12s} {len(g):>7,}   (표본부족)")
            continue
        r = np.exp(g.r) - 1
        print(f"    {name:<12s} {len(g):>7,} {r.mean()*100:>8.1f}% "
              f"{r.median()*100:>8.1f}% {(g.r > 0).mean()*100:>6.0f}%")


# ══════════════════════════════════════════════════════════
# ② CCF
# ══════════════════════════════════════════════════════════
def ccf_check():
    # 0~100 지수를 그대로 넣으면 sign()이 항상 +1이라 적중률이 나이브와 같아진다.
    # 50을 빼서 중심화하고, 역발상 방향(공포=매수)이므로 부호를 뒤집는다.
    def centered(s):
        return -(s.dropna() - 50)

    sigs = {'한국 공포탐욕': centered(FG[KR]), '미국 공포탐욕': centered(FG[US])}
    for c in FG.columns:
        if c.startswith('KR_c_'):
            sigs['└' + c[5:]] = centered(FG[c])
    _, strength, hits = fc.analyze(kospi(), sigs, horizons={'1M': 21, '1Y': 252})

    print(f"\n  CCF  (k>0 = 공포탐욕이 코스피를 선행, 단위 거래일)")
    print(f"    {'신호':<14s} {'peak_lag':>9s} {'peak_ccf':>9s} {'ccf0':>8s} {'유의':>5s}")
    for _, r in strength.iterrows():
        sig = 'O' if r.get('significant') else '-'
        print(f"    {r['signal']:<14s} {r['peak_lag']:>9.0f} {r['peak_ccf']:>9.3f} "
              f"{r['ccf0']:>8.3f} {sig:>5s}")

    print(f"\n  방향 적중률")
    print(f"    {'신호':<14s} {'기간':>5s} {'적중':>7s} {'나이브':>7s} {'우위':>8s} {'유효표본':>7s}")
    for _, r in hits.iterrows():
        print(f"    {r['signal']:<14s} {r['horizon']:>5s} {r['hit_rate']*100:>6.1f}% "
              f"{r['naive_base']*100:>6.1f}% {r['edge']*100:>+7.1f}%p {r['eff_n']:>7.0f}")


# ══════════════════════════════════════════════════════════
# ③ 편입 가치 — 대시보드 공식 그대로
# ══════════════════════════════════════════════════════════
def ridge_w(cols, tr, lams=(10, 30, 100)):
    X = tr[cols].values
    sd = X.std(0)
    sd[sd == 0] = 1
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


def build(ix, extra=()):
    P = df[f'{ix}_종가']
    y = np.log(P.shift(-12) / P)
    sig = list(m.signals_for(ix))
    for name, s_, prior in extra:
        sig.append((name, s_.reindex(df.index), prior, None, None))
    Z, IC, NOBS = {}, {}, {}
    for t in sig:
        n, s_, base = t[0], t[1], t[2]
        if s_ is None:
            continue
        xx = pd.concat([ez(s_) * base, y], axis=1, sort=True).dropna()
        r = xx.iloc[:, 0].corr(xx.iloc[:, 1]) if len(xx) > 40 else 0.0
        eff = abs(base) if n in FORCED else (base if r >= 0 else -base)
        Z[n], IC[n], NOBS[n] = ez(s_) * eff, abs(float(r)), len(xx)
    Z = pd.DataFrame(Z).ffill(limit=3)
    keep = [c for c in Z.columns
            if IC[c] >= 0.10 and NOBS.get(c, 0) >= 60 and c not in REF]
    return Z, IC, NOBS, keep, y


def weights_from(Z, IC, keep, tr):
    rw = ridge_w(keep, tr)
    w = pd.Series({c: IC[c] * float(rw[c]) for c in keep})
    CC = tr[keep].corr().abs()
    for c in keep:
        ac = (CC[c].sum() - 1) / (len(keep) - 1) if len(keep) > 1 else 0.0
        w[c] = w[c] / (1 + ac)
    return w / w.sum()


def oos(ix, extra=(), split='2015'):
    Z, IC, NOBS, keep, y = build(ix, extra)
    D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
    tr, te = D[D.index <= split], D[D.index > split]
    if len(tr) < 40 or len(te) < 20:
        return None
    w = weights_from(Z, IC, keep, tr)
    return float((te[keep] * w).sum(axis=1).corr(te['_y']))


def inclusion(ix):
    print("=" * 78)
    print(f"  ③ 편입 검증 — {ix}")
    print("=" * 78)
    # 가설: 탐욕이 높을수록 이후 12개월 수익이 나쁘다 → prior -1
    cands = [('공포탐욕(한국)', monthly(KR), -1),
             ('공포탐욕(미국)', monthly(US), -1)]
    Z, IC, NOBS, keep, y = build(ix, cands)

    print(f"\n  단독 IC 및 편입 필터  (통과 기준 |IC|≥0.10 & ≥60개월)")
    for n, _, _ in cands:
        print(f"    {n:<14s} IC={IC.get(n, float('nan')):.3f}  "
              f"n={NOBS.get(n, 0):>3d}개월  {'O 통과' if n in keep else 'X 탈락'}")

    print(f"\n  기존 신호와의 상관 (절대값 상위 5)")
    for n, _, _ in cands:
        if n not in Z:
            continue
        others = [c for c in keep if c != n]
        cc = Z[others].corrwith(Z[n]).abs().sort_values(ascending=False)
        print(f"    · {n}   평균절대상관 {cc.mean():.3f}")
        for k, v in cc.head(5).items():
            print(f"        {k:<18s} {v:.3f}{'   <- 중복 우려' if v > 0.7 else ''}")

    if any(n in keep for n, _, _ in cands):
        D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
        w = weights_from(Z, IC, keep, D)
        print(f"\n  공식이 내놓는 가중치 (전 표본)")
        for n in w.sort_values(ascending=False).index:
            print(f"    {n:<18s} {w[n]*100:5.2f}%   (단독IC {IC[n]:.3f})"
                  f"{'  <<<' if '공포탐욕' in n else ''}")

    base = oos(ix)
    print(f"\n  표본외 IC (2015년 이전 학습 -> 이후 검증)")
    print(f"    기존만            {base:+.4f}")
    for n, s_, p in cands:
        v = oos(ix, [(n, s_, p)])
        print(f"    +{n:<15s} {v:+.4f}   ({v - base:+.4f} "
              f"{'개선' if v > base else '악화'})")
    v = oos(ix, cands)
    print(f"    +둘 다            {v:+.4f}   ({v - base:+.4f} "
          f"{'개선' if v > base else '악화'})")


def nonlinear_test(ix='KOSPI'):
    """구간별 성과는 강한데 선형 IC가 약하다면, 관계가 비선형이라는 뜻이다.
    극단에서만 켜지는 변형들이 필터를 통과하는지 본다."""
    print("\n" + "=" * 78)
    print("  ④ 비선형 변형 — 극단에서만 켜지는 신호로 바꾸면 통과하나")
    print("=" * 78)
    P = df[f'{ix}_종가']
    y = np.log(P.shift(-12) / P)

    base = monthly(KR)
    variants = {
        '원본(선형)': base,
        '중심화 |x|': (base - 50),
        '극단만(25/75)': (base - 50).where((base < 25) | (base > 75), 0.0),
        '극단만(20/80)': (base - 50).where((base < 20) | (base > 80), 0.0),
        '제곱(부호유지)': (base - 50) * (base - 50).abs() / 50,
    }
    print(f"\n    {'변형':<16s} {'IC':>7s} {'n':>5s}   {'통과':>5s}")
    for name, s_ in variants.items():
        xx = pd.concat([ez(s_) * -1, y], axis=1, sort=True).dropna()
        r = xx.iloc[:, 0].corr(xx.iloc[:, 1])
        ok = 'O' if abs(r) >= 0.10 and len(xx) >= 60 else 'X'
        print(f"    {name:<16s} {abs(r):>7.3f} {len(xx):>5d}   {ok:>5s}")

    # 이미 대시보드에 있는 재료를 뺀 '순수 심리' 버전도 본다
    pure = FG[[c for c in FG.columns
               if c.startswith('KR_c_') and c[5:] in ('풋콜비율', '안전자산선호',
                                                      '모멘텀', '52주위치')]]
    ps = pure.mean(axis=1).resample('ME').last()
    xx = pd.concat([ez(ps) * -1, y], axis=1, sort=True).dropna()
    print(f"\n    기존 재료(VKOSPI·레버리지·신용스프레드) 제외한 4요소 버전")
    print(f"      IC = {abs(xx.iloc[:, 0].corr(xx.iloc[:, 1])):.3f}   n={len(xx)}개월")


if __name__ == '__main__':
    print("=" * 78)
    print("  ① 투자 성과 — 공포탐욕 구간별 이후 12개월 (코스피)")
    print("=" * 78)
    perf(KR, '한국 공포탐욕')
    perf(US, '미국 공포탐욕')

    print("\n" + "=" * 78)
    print("  ② CCF — 코스피 선행/후행")
    print("=" * 78)
    ccf_check()

    print()
    inclusion('KOSPI')
    nonlinear_test('KOSPI')
