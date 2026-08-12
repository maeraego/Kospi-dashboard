# -*- coding: utf-8 -*-
"""
check_credit_regime.py — 신용융자/예탁금의 레벨 z-score 구조 오염 점검

문제: 1998~2004년 이 비율은 평균 0.041로, 지금(0.28~0.35)과 완전히 다른 시장 구조였다.
      (당시 신용융자 제도·규모가 지금과 다름). 레벨 expanding z 는 이 옛 구간을 평균에
      섞어 넣어, '최근 5년 기준으로는 최저 수준(1.7 백분위)'인 현재를 z=+0.28(불리)로 표시한다.

이 프로젝트엔 같은 문제의 선례와 해법이 이미 있다 — 예상PER:
  "레벨 z-score는 이익 전망이 구조적으로 바뀌면 오염된다. 자기 추세(5년 이동평균) 대비
   괴리로 보면 훨씬 잘 잡는다 (단독 IC 0.136 → 0.259)."
같은 처방을 신용융자/예탁금에도 적용해 비교한다.

  A안 레벨 z        : ez(비율)                      ← 현재 배포된 방식
  B안 추세 대비 괴리 : log(비율) − log(비율).rolling(60).mean()
  C안 5년 롤링 z     : (비율 − 5년평균) / 5년표준편차
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
ez = m.ez
ratio = df['신용융자/예탁금']

VARIANTS = {
    'A 레벨 z (현재 배포)': ratio,
    'B 추세괴리(5년MA)':    np.log(ratio) - np.log(ratio).rolling(60, min_periods=36).mean(),
    'C 5년 롤링 z':         (ratio - ratio.rolling(60, min_periods=36).mean())
                            / ratio.rolling(60, min_periods=36).std(),
}


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


def assemble(variant_series, ix='KOSPI'):
    P = df[f'{ix}_종가']
    y = np.log(P.shift(-12) / P)
    sig = [t for t in m.signals_for(ix) if t[0] != '신용융자/예탁금']
    sig.append(('신용융자/예탁금', variant_series, -1, None, None))
    Z, IC, NOBS = {}, {}, {}
    for t in sig:
        n, s_, base = t[0], t[1], t[2]
        if s_ is None:
            continue
        xx = pd.concat([ez(s_) * base, y], axis=1, sort=True).dropna()
        r = xx.iloc[:, 0].corr(xx.iloc[:, 1]) if len(xx) > 40 else 0.0
        eff = abs(base) if n in ('한국VIX', 'VIX 급등(YoY)') else (base if r >= 0 else -base)
        Z[n] = ez(s_) * eff
        IC[n] = abs(float(r))
        NOBS[n] = len(xx)
    Z = pd.DataFrame(Z).ffill(limit=3)
    REF = {'시가총액/M2', 'M2/M1 비율', '수출 YoY', 'M2 증가율(YoY)'}
    keep = [c for c in Z.columns if IC[c] >= 0.10 and NOBS.get(c, 0) >= 60 and c not in REF]
    return Z, IC, NOBS, keep, y


def weights(Z, IC, keep, D):
    rw = ridge_w(keep, D)
    w = pd.Series({c: IC[c] * float(rw[c]) for c in keep})
    CC = D[keep].corr().abs()
    for c in keep:
        ac = (CC[c].sum() - 1) / (len(keep) - 1) if len(keep) > 1 else 0.0
        w[c] = w[c] / (1 + ac)
    return w / w.sum()


print("=" * 78)
print("  신용융자/예탁금 — 변환 방식별 비교 (KOSPI)")
print("=" * 78)
for lab, s in VARIANTS.items():
    Z, IC, NOBS, keep, y = assemble(s)
    D = pd.concat([Z[keep], y.rename('_y')], axis=1, sort=True).dropna()
    w = weights(Z, IC, keep, D)
    oos = {}
    for sp in ('2012', '2014', '2016', '2018', '2020'):
        tr, te = D[D.index <= sp], D[D.index > sp]
        if len(tr) < 40 or len(te) < 20:
            continue
        rw = ridge_w(keep, tr)
        ww = pd.Series({c: IC[c] * rw[c] for c in keep})
        CC = tr[keep].corr().abs()
        for c in keep:
            ac = (CC[c].sum() - 1) / (len(keep) - 1) if len(keep) > 1 else 0.0
            ww[c] = ww[c] / (1 + ac)
        ww = ww / ww.sum()
        oos[sp] = float((te[keep] * ww).sum(axis=1).corr(te['_y']))
    cz = Z['신용융자/예탁금'].dropna()
    cur = float(cz.iloc[-1])
    print(f"\n[{lab}]")
    print(f"   단독 IC      {IC['신용융자/예탁금']:.3f}   표본 {NOBS['신용융자/예탁금']}개월"
          f"   가중 {w.get('신용융자/예탁금', 0)*100:.1f}%")
    print(f"   현재 강세z   {cur:+.2f}  →  {'유리' if cur > 0 else '불리'}"
          f"   (백분위 {float((cz < cur).mean())*100:.1f}%)")
    print(f"   표본외 IC    " + "  ".join(f"{k}:{v:+.3f}" for k, v in oos.items())
          + f"   평균 {np.mean(list(oos.values())):+.3f}")
