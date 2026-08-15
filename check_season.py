# -*- coding: utf-8 -*-
"""
계절성(핼러윈 효과) 검증 — "5~10월 지옥, 11~4월 천국"이 사실인가

  · 월별 수익률 테이블 (평균·중앙·승률·t)
  · 겨울(11~4월) vs 여름(5~10월) 구간 비교 · 시즌별 연도 표
  · 하위기간 안정성 / 위기구간 제외 강건성
  · 백테스트: 매수후보유 vs 겨울만보유
  · 대시보드 레짐점수와의 결합 (12개월 지평에서 계절성이 상쇄되는지 포함)

사용: C:\\python312\\python.exe check_season.py [--full]
      --full 을 붙이면 build_dashboard 를 임포트해 레짐점수 결합분석까지 수행(느림).
"""
import sys, os
try: sys.stdout.reconfigure(encoding='utf-8')
except Exception: pass
import numpy as np, pandas as pd
from scipy import stats
import numpy.linalg as la

HERE = os.path.dirname(os.path.abspath(__file__))
ASOF = None            # None이면 마지막 '완결된' 월까지 자동
WMO  = {11, 12, 1, 2, 3, 4}          # 겨울(천국) 구간
SMO  = {5, 6, 7, 8, 9, 10}           # 여름(지옥) 구간
MN   = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
COST = 0.15                          # 편도 거래비용 %


def load():
    m = pd.read_parquet(os.path.join(HERE, 'krx_monthly.parquet'))
    m.index = pd.to_datetime(m.index)
    # 월말 parquet은 진행중인 당월도 담고 있다 → 미완월 제외(안 하면 그 달만 반쪽 수익률)
    d = pd.read_parquet(os.path.join(HERE, 'krx_daily.parquet'))
    last = pd.to_datetime(d.index).max()
    cut = ASOF or (last.to_period('M').to_timestamp('M') - pd.offsets.MonthEnd(1)
                   if last != last.to_period('M').to_timestamp('M') else last)
    m = m.loc[:cut]
    return m, {k: m[f'{k}_종가'].dropna().pct_change().dropna() * 100 for k in ('KOSPI', 'KOSDAQ')}


def month_table(r, label):
    print(f'\n{"="*80}\n■ {label}  ({r.index[0]:%Y-%m} ~ {r.index[-1]:%Y-%m}, n={len(r)})\n{"="*80}')
    print(f'{"월":>4} {"n":>4} {"평균%":>8} {"중앙%":>8} {"승률%":>7} {"σ":>7} {"t":>6} {"p":>6} {"최고%":>8} {"최저%":>8}')
    for i in range(1, 13):
        g = r[r.index.month == i]
        t, p = stats.ttest_1samp(g, 0)
        print(f'{MN[i-1]:>4} {len(g):>4} {g.mean():>8.2f} {g.median():>8.2f} {(g>0).mean()*100:>7.1f} '
              f'{g.std():>7.2f} {t:>6.2f} {p:>6.3f} {g.max():>8.1f} {g.min():>8.1f}')
    print(f'{"전체":>4} {len(r):>4} {r.mean():>8.2f} {r.median():>8.2f} {(r>0).mean()*100:>7.1f} {r.std():>7.2f}')


def split_compare(r, k):
    print(f'\n▶ {k}  ({r.index[0]:%Y-%m}~{r.index[-1]:%Y-%m})')
    print(f'{"구간":>14} {"개월":>5} {"월평균%":>8} {"중앙%":>7} {"승률%":>7} {"σ":>6} {"누적%":>10} {"연율%":>7}')
    WIN = {'11~4월(겨울)': WMO, '5~10월(여름)': SMO,
           '4~10월': {4,5,6,7,8,9,10}, '11~3월': {11,12,1,2,3}}
    G = {}
    for nm, mo in WIN.items():
        g = r[r.index.month.isin(mo)]; G[nm] = g
        cum = (1 + g/100).prod()
        print(f'{nm:>14} {len(g):>5} {g.mean():>8.2f} {g.median():>7.2f} {(g>0).mean()*100:>7.1f} '
              f'{g.std():>6.2f} {(cum-1)*100:>10.1f} {(cum**(12/len(g))-1)*100:>7.2f}')
    a, b = G['11~4월(겨울)'], G['5~10월(여름)']
    t, p = stats.ttest_ind(a, b, equal_var=False)
    _, pu = stats.mannwhitneyu(a, b)
    print(f'   겨울−여름 = {a.mean()-b.mean():+.2f}%p  t={t:.2f} p={p:.4f} (Mann-Whitney p={pu:.4f})')


def season_series(r):
    """겨울시즌 = 전년11월~당년4월(라벨은 4월이 속한 해), 여름시즌 = 당년5~10월"""
    w, s = {}, {}
    for dt, v in r.items():
        y, mo = dt.year, dt.month
        if mo >= 11:  w.setdefault(y+1, []).append(v)
        elif mo <= 4: w.setdefault(y, []).append(v)
        else:         s.setdefault(y, []).append(v)
    f = lambda d: pd.Series({y: ((1+np.array(v)/100).prod()-1)*100
                             for y, v in d.items() if len(v) == 6}).sort_index()
    return f(w), f(s)


def robustness(r, k):
    """대형위기 구간(여름에 몰려 있음)을 빼도 효과가 남는지 + 절사평균"""
    CRISIS = [('1997-07','1998-12'), ('2000-01','2000-12'), ('2008-01','2009-03'), ('2020-02','2020-04')]
    mask = pd.Series(True, index=r.index)
    for a, b in CRISIS: mask.loc[a:b] = False
    for nm, rr in [('전체', r), ('위기제외', r[mask])]:
        a = rr[rr.index.month.isin(WMO)]; b = rr[rr.index.month.isin(SMO)]
        t, p = stats.ttest_ind(a, b, equal_var=False)
        ta, tb = stats.trim_mean(a, .1), stats.trim_mean(b, .1)
        print(f'{k:>7} {nm:>6} n={len(rr):>3}  겨울 {a.mean():>6.2f} 여름 {b.mean():>6.2f} '
              f'차 {a.mean()-b.mean():>5.2f}%p (t={t:.2f} p={p:.3f}) | '
              f'절사평균 겨울 {ta:>5.2f} 여름 {tb:>5.2f} 차 {ta-tb:>5.2f}')


def backtest(r, k, cash):
    isw = pd.Series(r.index.month.isin(WMO), index=r.index)
    sw = pd.Series(np.where(isw, r, cash), index=r.index)
    trade = isw.astype(int).diff().abs().fillna(0)
    rows = [('매수후보유', r), ('겨울만보유(비용0)', sw),
            (f'겨울만보유(왕복{COST*2:.1f}%)', sw - trade*COST),
            ('여름만보유', pd.Series(np.where(~isw, r, cash), index=r.index))]
    print(f'\n▶ {k} ({r.index[0]:%Y-%m}~{r.index[-1]:%Y-%m}, {len(r)/12:.1f}년, 현금=CD91)')
    print(f'{"전략":>22} {"누적%":>12} {"CAGR%":>8} {"연변동%":>8} {"샤프":>7} {"MDD%":>8}')
    for nm, x in rows:
        yrs = len(x)/12; cagr = (1+x/100).prod()**(1/yrs)-1
        sd = x.std()*np.sqrt(12)/100
        eq = (1+x/100).cumprod()
        print(f'{nm:>22} {((1+x/100).prod()-1)*100:>12.0f} {cagr*100:>8.2f} {sd*100:>8.1f} '
              f'{cagr/sd:>7.2f} {(eq/eq.cummax()-1).min()*100:>8.1f}')


def wfrac(ts, h=6):
    return np.mean([(ts + pd.DateOffset(months=i)).month in WMO for i in range(1, h+1)])


def with_regime(R, cash, cut):
    """대시보드 레짐점수와의 관계 — 12개월 지평에선 상쇄되고, 6개월 지평에선 직교 가산."""
    import build_dashboard as bd
    print('\n' + '#'*80); print('# 12개월 선행수익 vs 진입월 (대시보드 예측지평)'); print('#'*80)
    for k in ('KOSPI', 'KOSDAQ'):
        y12 = (bd.fwd(k, 12).dropna().loc[:cut]) * 100
        a = y12[y12.index.month.isin([10,11,12,1,2,3])]; b = y12[y12.index.month.isin([4,5,6,7,8,9])]
        t, p = stats.ttest_ind(a, b, equal_var=False)
        print(f'  {k:>7} 겨울진입 {a.mean():>5.1f}% vs 여름진입 {b.mean():>5.1f}%  '
              f'차 {a.mean()-b.mean():+.1f}%p  t={t:.2f} p={p:.3f}  → 12개월 창은 12개월 전부를 담아 계절성이 상쇄')

    print('\n' + '#'*80); print('# 6개월 선행수익: 레짐점수 vs 겨울비중 (중첩·룩어헤드 교정)'); print('#'*80)
    A = {}
    for k in ('KOSPI', 'KOSDAQ'):
        a = bd.analyze(k); A[k] = a
        sc = a['sc'].loc[:cut]; y6 = bd.fwd(k, 6).dropna().loc[:cut]*100
        d = pd.concat([sc.rename('sc'), y6.rename('y')], axis=1).dropna()
        d['wf'] = [wfrac(t) for t in d.index]
        print(f'\n▶ {k} (n={len(d)})  진입월별 이후6개월 평균수익(겨울비중)')
        for a0, b0 in ((1, 7), (7, 13)):
            print('   ' + '  '.join(f'{i:>2}월말 {d[d.index.month==i]["y"].mean():>6.1f}%({d[d.index.month==i]["wf"].mean():.2f})'
                                    for i in range(a0, b0)))
        pw, ps = d[d.index.month == 10]['y'], d[d.index.month == 4]['y']
        t, p = stats.ttest_ind(pw, ps, equal_var=False)
        print(f'  순수 겨울창(10월말→4월말) {pw.mean():+.1f}% vs 순수 여름창(4월말→10월말) {ps.mean():+.1f}%'
              f'  차 {pw.mean()-ps.mean():+.1f}%p t={t:.2f} p={p:.3f}')
        print(f'  IC: 레짐점수 {d["sc"].corr(d["y"],method="spearman"):+.3f} / 겨울비중 {d["wf"].corr(d["y"],method="spearman"):+.3f}'
              f' | 둘의 상관 {d["sc"].corr(d["wf"]):+.3f} (≈0 → 직교, 가산 가능)')
        X = np.column_stack([np.ones(len(d)), stats.zscore(d['sc']), d['wf']-0.5]); y = d['y'].values
        b_, *_ = la.lstsq(X, y, rcond=None); res = y - X@b_
        u = res[:, None]*X; S = u.T@u                       # Newey-West(중첩 6개월)
        for l in range(1, 7):
            G = u[l:].T@u[:-l]; S += (1-l/7)*(G+G.T)
        XtXi = la.inv(X.T@X); nw = np.sqrt(np.diag(XtXi@S@XtXi))
        print(f'  회귀 y6 = {b_[0]:.1f} + {b_[1]:.1f}·z(점수)[NW t={b_[1]/nw[1]:.2f}] '
              f'+ {b_[2]:.1f}·(겨울비중−0.5)[NW t={b_[2]/nw[2]:.2f}]')

    print('\n' + '#'*80); print('# 결합 백테스트 (신호 1개월 지연 = 룩어헤드 제거, 레짐가중은 전기간 IC라 낙관적)'); print('#'*80)
    for k in ('KOSPI', 'KOSDAQ'):
        r = R[k]; sc = A[k]['sc']
        epct = sc.expanding(36).apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
        sig = epct.reindex(r.index).ffill().shift(1)
        cc = cash.reindex(r.index)
        isw = pd.Series(r.index.month.isin(WMO), index=r.index)
        reg = (sig >= 0.5).fillna(False)
        strat = {'매수후보유': pd.Series(1.0, index=r.index), '레짐만(백분위≥50)': reg.astype(float),
                 '계절만(11~4월)': isw.astype(float), '레짐+계절(AND)': (reg & isw).astype(float),
                 '레짐or계절(OR)': (reg | isw).astype(float)}
        start = sig.dropna().index[0]
        print(f'\n▶ {k} ({start:%Y-%m}~{r.index[-1]:%Y-%m})')
        print(f'{"전략":>18} {"CAGR%":>8} {"연변동%":>8} {"샤프":>7} {"MDD%":>8} {"주식%":>7} {"연매매":>7}')
        for nm, w in strat.items():
            w = w.reindex(r.index).fillna(0).loc[start:].clip(0, 1)
            x = w*r.loc[start:] + (1-w)*cc.loc[start:] - w.diff().abs().fillna(0)*COST
            yrs = len(x)/12; cagr = (1+x/100).prod()**(1/yrs)-1; sd = x.std()*np.sqrt(12)/100
            eq = (1+x/100).cumprod()
            print(f'{nm:>18} {cagr*100:>8.2f} {sd*100:>8.1f} {cagr/sd:>7.2f} '
                  f'{(eq/eq.cummax()-1).min()*100:>8.1f} {w.mean()*100:>7.1f} {w.diff().abs().sum()/yrs:>7.2f}')


def main():
    m, R = load()
    cut = m.index[-1]
    e = pd.read_parquet(os.path.join(HERE, 'ecos_monthly.parquet')); e.index = pd.to_datetime(e.index)
    cash = (e['CD91'].reindex(R['KOSPI'].index).ffill()/12).fillna(0.25)

    for k in ('KOSPI', 'KOSDAQ'):
        month_table(R[k], f'{k} 월별 수익률')

    print('\n\n' + '#'*80); print('# 구간 비교'); print('#'*80)
    for k in ('KOSPI', 'KOSDAQ'): split_compare(R[k], k)

    print('\n\n' + '#'*80); print('# 시즌별(연도) 수익률'); print('#'*80)
    for k in ('KOSPI', 'KOSDAQ'):
        w, s = season_series(R[k]); yrs = sorted(set(w.index) & set(s.index))
        ww, ss = w[yrs], s[yrs]
        print(f'\n▶ {k}   겨울평균 {ww.mean():+.2f}% / 여름평균 {ss.mean():+.2f}% / 차 {ww.mean()-ss.mean():+.2f}%p')
        print(f'  겨울>여름 {int((ww>ss).sum())}/{len(yrs)}년 = {(ww>ss).mean()*100:.1f}%  |  '
              f'플러스비율 겨울 {(ww>0).mean()*100:.1f}% 여름 {(ss>0).mean()*100:.1f}%')
        t, p = stats.ttest_rel(ww, ss); _, wp = stats.wilcoxon(ww, ss)
        print(f'  대응표본 t={t:.2f} p={p:.4f} (Wilcoxon p={wp:.4f})')
        for y in yrs:
            print(f'    {y}  겨울 {w[y]:>7.1f}%   여름 {s[y]:>7.1f}%   {"O" if w[y]>s[y] else "X"}')

    print('\n\n' + '#'*80); print('# 하위기간 안정성 (월평균 %)'); print('#'*80)
    PER = [('1995~2004','1995','2004-12-31'), ('2005~2014','2005','2014-12-31'),
           ('2015~현재','2015',None), ('최근10년','2016',None), ('최근5년','2021',None)]
    for k in ('KOSPI', 'KOSDAQ'):
        print(f'\n▶ {k}')
        print(f'{"기간":>12} {"n":>5} {"겨울%":>8} {"여름%":>8} {"차이%p":>8} {"t":>6} {"p":>6}')
        for nm, s0, s1 in PER:
            r = R[k].loc[s0:s1 or cut]
            if len(r) < 24: continue
            a = r[r.index.month.isin(WMO)]; b = r[r.index.month.isin(SMO)]
            t, p = stats.ttest_ind(a, b, equal_var=False)
            print(f'{nm:>12} {len(r):>5} {a.mean():>8.2f} {b.mean():>8.2f} {a.mean()-b.mean():>8.2f} {t:>6.2f} {p:>6.3f}')

    print('\n\n' + '#'*80); print('# 강건성 (위기구간 제외 · 절사평균)'); print('#'*80)
    for k in ('KOSPI', 'KOSDAQ'): robustness(R[k], k)

    print('\n\n' + '#'*80); print('# 백테스트'); print('#'*80)
    for k in ('KOSPI', 'KOSDAQ'): backtest(R[k], k, cash.reindex(R[k].index).ffill())

    if '--full' in sys.argv:
        with_regime(R, cash, cut)


if __name__ == '__main__':
    main()
