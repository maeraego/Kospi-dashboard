# -*- coding: utf-8 -*-
"""
check_tails.py  -  꼬리 두께 진단: 시그마를 써도 되는 곳과 안 되는 곳

문제제기: 주식 수익률은 꼬리가 두꺼운데(멱급수) 대시보드는 켈리·z스코어·
리지 표준화에 표준편차를 쓴다. 괜찮은가?

핵심은 '어느 빈도의 수익률이냐'다.
  일간   -> 꼬리 매우 두꺼움
  12개월 -> 모델의 실제 예측 대상. 합산되며 정규에 가까워진다(CLT)
그리고 '시그마를 부풀리는 것이 상방이냐 하방이냐'가 켈리에서는 결정적이다.

사용법:  C:/python312/python.exe check_tails.py
"""
import io, sys, contextlib
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    import build_dashboard as bd
df = bd.df
NAMES = ['매우불리', '불리', '중립', '유리', '매우유리']


def hill(x, frac=.10):
    """Hill 꼬리지수. 작을수록 두껍고, 2 이하면 이론상 분산이 무한."""
    a = np.sort(np.abs(x[np.isfinite(x)]))[::-1]
    k = min(max(10, int(len(a) * frac)), len(a) - 1)
    return float(1.0 / np.mean(np.log(a[:k] / a[k]))) if k >= 10 else np.nan


def spearman(a, b):
    """순위 피어슨 = 스피어만. scipy 없이."""
    return a.rank().corr(b.rank())


def describe(x, lab):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    m, s = x.mean(), x.std(ddof=1)
    z = (x - m) / s
    mad = float(np.median(np.abs(x - np.median(x))) * 1.4826)
    print(f'  {lab:22s} n={len(x):5d}  sd={s:6.4f}  MAD={mad:6.4f}'
          f'  sd/MAD={s/mad:4.2f}')
    print(f'  {"":22s} 왜도{float((z**3).mean()):+6.2f}'
          f'  초과첨도{float((z**4).mean()-3):+7.2f}'
          f'  |z|>3 {np.mean(np.abs(z)>3)*100:4.2f}%(정규0.27%)'
          f'  alpha={hill(x-m):4.2f}')


def buckets(ix):
    """국면별 (라벨, 12개월 수익 배열, 무위험수익률)."""
    a = bd.analyze(ix)
    r12 = df[f'{ix}_종가'].pct_change(12).shift(-12)
    rf = (df['국고채3년'] / 100.0) if '국고채3년' in df else pd.Series(0.0, index=df.index)
    S = pd.concat([a['sc'].rename('s'), r12.rename('r'), rf.rename('rf')],
                  axis=1).dropna()
    e = np.quantile(S['s'], [.2, .4, .6, .8])
    S['b'] = np.digitize(S['s'], e)
    for b in range(5):
        g = S[S['b'] == b]
        if len(g) >= 10:
            yield NAMES[b], g['r'].values, float(g['rf'].mean())


def kelly_emp(r, rf=0.0, lo=-.5, hi=1.5, n=801):
    """경험분포에서 E[log(1+f(r-rf))] 최대화. 분포가정 없음."""
    best, bf = -1e18, 0.0
    for f in np.linspace(lo, hi, n):
        w = 1.0 + f * (r - rf)
        if (w <= 1e-9).any():
            continue
        v = float(np.mean(np.log(w)))
        if v > best:
            best, bf = v, f
    return bf


print('=' * 76)
print('1) 빈도별 꼬리 두께 - 12개월로 합산하면 얼마나 정규에 가까워지나')
print('=' * 76)
daily = pd.read_parquet('krx_daily.parquet')
for ix in ('KOSPI', 'KOSDAQ'):
    print(f'\n[{ix}]')
    c = [c for c in daily.columns if c.startswith(ix) and '종가' in c]
    if c:
        describe(np.log(daily[c[0]].dropna()).diff().dropna(), '일간')
    p = df[f'{ix}_종가'].dropna()
    describe(np.log(p).diff().dropna(), '월간')
    describe(np.log(p).diff(12).shift(-12).dropna(), '12개월(중첩)')
    describe(np.log(p).diff(12).dropna().iloc[::12], '12개월(비중첩)')

print()
print('=' * 76)
print('2) 연속형 켈리 - 시그마식 vs 경험분포 vs 하방반편차')
print('   켈리는 하방 위험만 벌해야 맞다. sd 는 상방까지 같이 벌한다.')
print('=' * 76)
for ix in ('KOSPI', 'KOSDAQ'):
    print(f'\n[{ix}] {"국면":9s} {"mu":>7s} {"sd":>6s} {"상방":>6s} {"하방":>6s}'
          f' {"f_sd":>6s} {"f_경험":>7s} {"f_하방":>7s}')
    for nm, r, rf in buckets(ix):
        mu, sd = r.mean(), r.std(ddof=1)
        up, dn = r[r > mu], r[r < mu]
        usd = np.sqrt(((up - mu) ** 2).sum() / (len(r) - 1)) if len(up) else 0
        dsd = np.sqrt(((dn - mu) ** 2).sum() / (len(r) - 1)) if len(dn) else 0
        f_sd = np.clip((mu - rf) / sd ** 2, -.5, 1.5)
        f_dn = np.clip((mu - rf) / dsd ** 2, -.5, 1.5) if dsd > 1e-9 else 1.5
        print(f'     {nm:9s} {mu:+7.3f} {sd:6.3f} {usd:6.3f} {dsd:6.3f}'
              f' {f_sd:6.2f} {kelly_emp(r, rf):7.2f} {f_dn:7.2f}')

print()
print('=' * 76)
print('3) 정규가정 VaR vs 실제 - 5% 지점과 최악값을 함께 본다')
print('=' * 76)
for ix in ('KOSPI', 'KOSDAQ'):
    print(f'\n[{ix}] {"국면":9s} {"정규5%":>8s} {"실제5%":>8s} {"실제최악":>9s}')
    for nm, r, _ in buckets(ix):
        mu, sd = r.mean(), r.std(ddof=1)
        print(f'     {nm:9s} {mu-1.645*sd:+8.3f} {np.percentile(r,5):+8.3f}'
              f' {r.min():+9.3f}')

print()
print('=' * 76)
print('4) z스코어 표준화 - 표준편차 vs 로버스트(MAD) 예측력 비교')
print('=' * 76)


def z_std(s, minp=36):
    return (s - s.expanding(minp).mean()) / s.expanding(minp).std()


def z_rob(s, minp=36):
    med = s.expanding(minp).median()
    mad = (s - med).abs().expanding(minp).median() * 1.4826
    return (s - med) / mad.replace(0, np.nan)


for ix in ('KOSPI', 'KOSDAQ'):
    fwd = np.log(df[f'{ix}_종가']).diff(12).shift(-12)
    rows = []
    for item in bd.signals_for(ix):
        nm = item[0]
        try:
            raw = pd.Series(item[1]).astype(float)
        except Exception:
            continue
        rec, ok = {'sig': nm}, True
        for lab, fn in (('std', z_std), ('rob', z_rob)):
            d = pd.concat([fn(raw).rename('z'), fwd.rename('f')], axis=1).dropna()
            if len(d) < 60:
                ok = False
                break
            rec[lab] = spearman(d['z'], d['f'])
        if ok:
            rows.append(rec)
    P = pd.DataFrame(rows).set_index('sig').dropna()
    if P.empty:
        continue
    P['차이'] = P['rob'].abs() - P['std'].abs()
    print(f'\n[{ix}] 신호 {len(P)}개')
    print(f'  평균 |IC|   표준편차 {P["std"].abs().mean():.4f}'
          f'   로버스트 {P["rob"].abs().mean():.4f}')
    print(f'  로버스트 우위 {int((P["차이"]>0).sum())}개 / {len(P)}개')
    P = P.sort_values('차이')
    for nm, r in pd.concat([P.head(3), P.tail(3)]).iterrows():
        print(f'    {str(nm)[:24]:24s} std {r["std"]:+.3f}  rob {r["rob"]:+.3f}'
              f'  차이 {r["차이"]:+.3f}')
