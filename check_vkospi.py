# -*- coding: utf-8 -*-
"""
check_vkospi.py — VKOSPI(내재변동성) vs 실현변동성(20일) 예측력 비교

물음: 대시보드의 변동성 신호를 실현변동성에서 VKOSPI로 바꾸면 더 나은가?

공정 비교 원칙:
  · 기존 실현변동성 IC 0.184 는 1995~ 표본이다. VKOSPI는 2003~ 뿐이므로
    두 지표를 **같은 기간(2003~)** 으로 잘라 비교한다. 안 그러면 표본 차이를 성능 차이로 오해한다.
  · 방향은 둘 다 +1 고정(높을수록 강세). CLAUDE.md의 "공포에 사라" 원칙 —
    급락 진행 중 IC가 일시적으로 음수가 되어 바닥에서 '팔아라'로 뒤집히는 사고를 막기 위함.
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

df, ez = m.df, m.ez
REAL = '실현변동성(20일)'

vk = pd.read_parquet('vkospi_daily.parquet')['VKOSPI']
vk_m = vk.resample('ME').last().reindex(df.index)
df['VKOSPI'] = vk_m

P = df['KOSPI_종가']
y12 = np.log(P.shift(-12) / P)
real = df['KOSPI_변동성']

START = vk_m.dropna().index.min()
print(f"[표본] VKOSPI {START.date()} ~ {vk_m.dropna().index.max().date()}  "
      f"({vk_m.dropna().shape[0]}개월)")


def ic(sig, y, since=None):
    s = sig if since is None else sig.where(sig.index >= since)
    d = pd.concat([ez(s), y], axis=1, sort=True).dropna()
    return (float(d.iloc[:, 0].corr(d.iloc[:, 1])), len(d)) if len(d) > 40 else (np.nan, len(d))


print("\n" + "=" * 72)
print("  ① 단독 IC (강세방향 +1 고정, expanding z vs 향후 12개월 로그수익)")
print("=" * 72)
for lab, s in [(REAL, real), ('VKOSPI', vk_m)]:
    a, na = ic(s, y12)
    b, nb = ic(s, y12, START)
    print(f"  {lab:14s}  전기간 {a:+.3f} (n={na})   2003~ {b:+.3f} (n={nb})")
print("  ※ 아래 비교는 2003~ 공통 구간 기준")

print("\n" + "=" * 72)
print("  ② 두 지표의 관계")
print("=" * 72)
d = pd.concat([real.rename('real'), vk_m.rename('vk')], axis=1).dropna()
print(f"  월간 상관(수준)      {d['real'].corr(d['vk']):+.3f}")
print(f"  월간 상관(변화)      {d['real'].diff().corr(d['vk'].diff()):+.3f}")
print(f"  평균 수준            실현 {d['real'].mean():.1f}  vs  VKOSPI {d['vk'].mean():.1f}")
print(f"  현재                 실현 {d['real'].iloc[-1]:.1f}  vs  VKOSPI {d['vk'].iloc[-1]:.1f}"
      f"   (차이 {d['real'].iloc[-1]-d['vk'].iloc[-1]:+.1f})")

# 일별 선후관계: 실현변동성이 VKOSPI를 후행하는지
rd = (np.log(pd.read_parquet('krx_daily.parquet')['KOSPI_종가']).diff()
      .rolling(20).std() * np.sqrt(252) * 100)
dd = pd.concat([rd.rename('real'), vk.rename('vk')], axis=1).dropna()
best = max(range(-15, 16), key=lambda k: abs(dd['real'].corr(dd['vk'].shift(k))))
print(f"  일별 최대상관 시차   {best:+d}일  (상관 {dd['real'].corr(dd['vk'].shift(best)):+.3f})")
print(f"     해석: 양수면 VKOSPI를 그만큼 미래로 밀었을 때 실현변동성과 가장 맞음")
print(f"           = 실현변동성이 VKOSPI를 {abs(best)}일 후행")

print("\n" + "=" * 72)
print("  ③ 꼬리 검증 — 극단 진입 후 이후 12개월 수익 (2003~ 월말 기준)")
print("=" * 72)
for lab, s in [(REAL, real), ('VKOSPI', vk_m)]:
    ss = s.where(s.index >= START).dropna()
    pct = ss.rank(pct=True)
    print(f"\n  [{lab}]  현재 백분위 {float(pct.iloc[-1])*100:.1f}%")
    for name, mask in [('상위 10% (공포 극단)', pct > .90), ('전체', pct.notna()),
                       ('하위 10% (안심 극단)', pct <= .10)]:
        v = y12.reindex(ss.index)[mask].dropna()
        if len(v) < 10:
            print(f"     {name:20s} 표본부족"); continue
        print(f"     {name:20s} 평균 {v.mean()*100:+6.1f}%   승률 {(v>0).mean()*100:5.1f}%   n={len(v)}")


# ── 신호 교체 시 가중·표본외 ──
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


def build(mode):
    """mode: 'real'=현행, 'vkospi'=교체, 'both'=둘 다"""
    sig = [t for t in m.signals_for('KOSPI') if t[0] != REAL]
    if mode in ('real', 'both'):
        sig.append((REAL, real, +1, None, None))
    if mode in ('vkospi', 'both'):
        sig.append(('VKOSPI', vk_m, +1, None, None))
    Z, IC, NOBS = {}, {}, {}
    for t in sig:
        n, s_, base = t[0], t[1], t[2]
        if s_ is None:
            continue
        xx = pd.concat([ez(s_) * base, y12], axis=1, sort=True).dropna()
        r = xx.iloc[:, 0].corr(xx.iloc[:, 1]) if len(xx) > 40 else 0.0
        eff = abs(base) if n in (REAL, 'VKOSPI', 'VIX 급등(YoY)') else (base if r >= 0 else -base)
        Z[n] = ez(s_) * eff
        IC[n] = abs(float(r))
        NOBS[n] = len(xx)
    Z = pd.DataFrame(Z).ffill(limit=3)
    REF = {'시가총액/M2', 'M2/M1 비율', '수출 YoY', 'M2 증가율(YoY)'}
    keep = [c for c in Z.columns if IC[c] >= 0.10 and NOBS.get(c, 0) >= 60 and c not in REF]
    return Z, IC, keep


print("\n" + "=" * 72)
print("  ④ 신호 구성별 가중·표본외 IC")
print("=" * 72)
for mode, lab in [('real', '현행 (실현변동성만)'), ('vkospi', '교체 (VKOSPI만)'),
                  ('both', '둘 다 넣기')]:
    Z, IC, keep = build(mode)
    D = pd.concat([Z[keep], y12.rename('_y')], axis=1, sort=True).dropna()
    rw = ridge_w(keep, D)
    w = pd.Series({c: IC[c] * float(rw[c]) for c in keep})
    CC = Z[keep].corr().abs()
    for c in keep:
        w[c] = w[c] / (1 + (CC[c].sum() - 1) / (len(keep) - 1))
    w = w / w.sum()
    oos = []
    for sp in ('2014', '2016', '2018', '2020'):
        tr, te = D[D.index <= sp], D[D.index > sp]
        if len(tr) < 40 or len(te) < 20:
            continue
        r2 = ridge_w(keep, tr)
        ww = pd.Series({c: IC[c] * r2[c] for c in keep})
        C2 = tr[keep].corr().abs()
        for c in keep:
            ww[c] = ww[c] / (1 + (C2[c].sum() - 1) / (len(keep) - 1))
        ww = ww / ww.sum()
        oos.append(float((te[keep] * ww).sum(axis=1).corr(te['_y'])))
    vols = {k: w.get(k, 0) * 100 for k in (REAL, 'VKOSPI') if k in w.index}
    print(f"\n  [{lab}]  표본외 평균 {np.mean(oos):+.4f}   ({', '.join(f'{v:+.3f}' for v in oos)})")
    for k, v in vols.items():
        print(f"     {k:14s} 가중 {v:5.2f}%   단독IC {IC[k]:.3f}")
