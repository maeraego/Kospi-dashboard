# -*- coding: utf-8 -*-
"""
season_core.py — 계절성(핼러윈 효과) 계산 코어

  "5~10월 지옥 / 11~4월 천국"을 실증하고, 그 결과를 메인 대시보드가
  오버레이(참고지표)와 켈리 계절조정으로 쓸 수 있게 수치를 뽑아준다.

  · season_dashboard.py  — 이 모듈로 전용 대시보드(season_dashboard.html)를 만든다
  · build_dashboard.py   — 이 모듈로 계절 오버레이 패널 + 켈리 계절조정을 붙인다

  ★ scipy 를 쓰지 않는다.
    깃허브 액션(클라우드 빌드)은 pandas·numpy·pyarrow 만 설치한다. scipy 를 import 하면
    메인 대시보드 빌드가 통째로 깨진다. 그래서 t검정·절사평균을 여기서 직접 구현한다.

  ★ 미완월 처리
    krx_monthly.parquet 은 '진행 중인 당월'도 담고 있다(월중 값이 그대로 월말행에 들어감).
    그 달을 그대로 쓰면 반쪽짜리 수익률이 계절통계에 섞이므로 last_complete_month() 로 자른다.
"""
import math
import numpy as np
import pandas as pd

WMO = (11, 12, 1, 2, 3, 4)          # 겨울 = '천국' 구간
SMO = (5, 6, 7, 8, 9, 10)           # 여름 = '지옥' 구간
MN = ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월']

SHRINK = 0.5        # 계절 프리미엄 축소계수. 예측밴드의 국면프리미엄과 같은 관례(절반만 반영)
COST = 0.15         # 편도 거래비용 % (계절전략은 연 2회 매매 → 왕복 0.3%)

# 여름에 몰려 있는 대형 급락 — "계절성이 아니라 위기 몇 번 때문 아니냐"를 반증하기 위한 제외구간
CRISIS = [('1997-07', '1998-12', 'IMF'), ('2000-01', '2000-12', '닷컴붕괴'),
          ('2008-01', '2009-03', '금융위기'), ('2020-02', '2020-04', '코로나')]


# ── 통계 유틸 (scipy 대체) ────────────────────────────────────────────────
def _betacf(a, b, x, itmax=200, eps=3e-16):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300: d = 1e-300
    d = 1.0 / d; h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300: d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300: c = 1e-300
        d = 1.0 / d; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300: d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300: c = 1e-300
        d = 1.0 / d; de = d * c; h *= de
        if abs(de - 1.0) < eps: break
    return h


def _betainc(a, b, x):
    """정규화 불완전베타 I_x(a,b) — Student-t 분포함수용"""
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    lb = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
          + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lb) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lb) * _betacf(b, a, 1.0 - x) / b


def t_p(t, dfree):
    """양측 p값 (Student-t)"""
    if not np.isfinite(t) or dfree <= 0: return float('nan')
    return float(_betainc(dfree / 2.0, 0.5, dfree / (dfree + t * t)))


def welch(a, b):
    """이표본 Welch t검정 → (t, p). 분산이 다른 두 구간(겨울/여름)이라 등분산 가정 안 함."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    na, nb = len(a), len(b)
    if na < 3 or nb < 3: return float('nan'), float('nan')
    va, vb = a.var(ddof=1) / na, b.var(ddof=1) / nb
    t = (a.mean() - b.mean()) / math.sqrt(va + vb)
    dfree = (va + vb) ** 2 / (va ** 2 / (na - 1) + vb ** 2 / (nb - 1))
    return float(t), t_p(t, dfree)


def ttest1(a, mu=0.0):
    a = np.asarray(a, float); n = len(a)
    if n < 3: return float('nan'), float('nan')
    t = (a.mean() - mu) / (a.std(ddof=1) / math.sqrt(n))
    return float(t), t_p(t, n - 1)


def ttest_rel(a, b):
    """대응표본 — 같은 해의 겨울시즌 vs 여름시즌은 짝지어진 관측"""
    d = np.asarray(a, float) - np.asarray(b, float)
    return ttest1(d)


def trim_mean(a, frac=0.1):
    a = np.sort(np.asarray(a, float)); k = int(len(a) * frac)
    return float(a[k:len(a) - k].mean()) if len(a) - 2 * k > 0 else float(a.mean())


def kelly(vals, rf=0.0, lo=-3.0, hi=8.0, n=441):
    """경험분포 켈리 — build_dashboard._kelly_empirical 과 같은 격자탐색.
       계절 앵커용이라 상하한을 넓게 잡는다(±150% 로 자르면 f_전체가 상한에 붙어
       계절 효과가 통째로 사라진다). 메인에서 호출할 땐 kelly_fn 으로 정본을 주입한다."""
    r = np.asarray(vals, float); r = r[np.isfinite(r)]
    if len(r) < 5: return 0.0
    best, bf = -np.inf, 0.0
    for f in np.linspace(lo, hi, n):
        w = 1.0 + f * (r - rf)
        if (w <= 1e-9).any(): continue
        v = float(np.mean(np.log(w)))
        if v > best: best, bf = v, f
    return bf


# ── 데이터 준비 ──────────────────────────────────────────────────────────
def last_complete_month(daily_idx):
    """일별 데이터의 마지막 날짜로 '완결된 마지막 월말'을 판정."""
    last = pd.Timestamp(pd.to_datetime(daily_idx).max())
    eom = last.to_period('M').to_timestamp('M')
    return eom if last.normalize() == eom.normalize() else eom - pd.offsets.MonthEnd(1)


def monthly_returns(px, cut=None):
    """월말 종가 → 월 수익률 %. cut 이후(미완월 포함)는 버린다."""
    s = pd.Series(px).dropna()
    if cut is not None: s = s.loc[:cut]
    return s.pct_change().dropna() * 100


def is_winter(idx):
    return pd.Index(idx).month.isin(WMO)


def wfrac(ts, h=6):
    """ts(월말) 진입 후 h개월 중 겨울(11~4월)이 차지하는 비중.
       12개월(h=12)이면 항상 0.5 — 대시보드의 12개월 지평에서 계절성이 상쇄되는 이유."""
    ts = pd.Timestamp(ts)
    return float(np.mean([(ts + pd.DateOffset(months=i)).month in WMO for i in range(1, h + 1)]))


# ── 집계 ────────────────────────────────────────────────────────────────
def month_table(r):
    out = []
    for i in range(1, 13):
        g = r[r.index.month == i]
        t, p = ttest1(g.values)
        out.append(dict(m=i, name=MN[i - 1], n=len(g), mean=float(g.mean()),
                        med=float(g.median()), win=float((g > 0).mean() * 100),
                        sd=float(g.std()), t=t, p=p,
                        mx=float(g.max()), mn=float(g.min()),
                        winter=i in WMO))
    return out


def split_stats(r, months):
    g = r[r.index.month.isin(months)]
    cum = float((1 + g / 100).prod())
    return dict(n=len(g), mean=float(g.mean()), med=float(g.median()),
                win=float((g > 0).mean() * 100), sd=float(g.std()),
                cum=(cum - 1) * 100, ann=(cum ** (12 / len(g)) - 1) * 100, g=g)


def winter_vs_summer(r):
    w = split_stats(r, WMO); s = split_stats(r, SMO)
    t, p = welch(w['g'].values, s['g'].values)
    return dict(w=w, s=s, diff=w['mean'] - s['mean'], t=t, p=p)


def season_years(r):
    """겨울시즌 = 전년 11월~당년 4월(라벨 = 4월이 속한 해), 여름시즌 = 당년 5~10월.
       6개월이 다 차지 않은 시즌은 버린다(반쪽 시즌이 평균을 흔들지 않도록)."""
    W, S = {}, {}
    for dt, v in r.items():
        y, mo = dt.year, dt.month
        if mo >= 11:   W.setdefault(y + 1, []).append(v)
        elif mo <= 4:  W.setdefault(y, []).append(v)
        else:          S.setdefault(y, []).append(v)
    f = lambda d: {y: float(((1 + np.array(v) / 100).prod() - 1) * 100)
                   for y, v in d.items() if len(v) == 6}
    W, S = f(W), f(S)
    yrs = sorted(set(W) & set(S))
    ww = np.array([W[y] for y in yrs]); ss = np.array([S[y] for y in yrs])
    t, p = ttest_rel(ww, ss)
    return dict(years=yrs, w=ww, s=ss,
                wmean=float(ww.mean()), smean=float(ss.mean()),
                wmed=float(np.median(ww)), smed=float(np.median(ss)),
                wpos=float((ww > 0).mean() * 100), spos=float((ss > 0).mean() * 100),
                beat=int((ww > ss).sum()), nyr=len(yrs), t=t, p=p)


def subperiods(r, cut):
    PER = [('1995~2004', '1995', '2004-12-31'), ('2005~2014', '2005', '2014-12-31'),
           ('2015~현재', '2015', None), ('최근10년', '2016', None), ('최근5년', '2021', None)]
    out = []
    for nm, s0, s1 in PER:
        x = r.loc[s0:(s1 or cut)]
        if len(x) < 24: continue
        a = x[x.index.month.isin(WMO)]; b = x[x.index.month.isin(SMO)]
        t, p = welch(a.values, b.values)
        out.append(dict(name=nm, n=len(x), w=float(a.mean()), s=float(b.mean()),
                        diff=float(a.mean() - b.mean()), t=t, p=p))
    return out


def robustness(r):
    """대형위기 제외 + 절사평균 — 꼬리 몇 개가 만든 착시인지 검사"""
    mask = pd.Series(True, index=r.index)
    for a, b, _ in CRISIS: mask.loc[a:b] = False
    out = []
    for nm, x in [('전체', r), ('위기제외', r[mask])]:
        a = x[x.index.month.isin(WMO)]; b = x[x.index.month.isin(SMO)]
        t, p = welch(a.values, b.values)
        out.append(dict(name=nm, n=len(x), w=float(a.mean()), s=float(b.mean()),
                        diff=float(a.mean() - b.mean()), t=t, p=p,
                        tw=trim_mean(a.values), ts=trim_mean(b.values)))
    out[0]['tdiff'] = out[0]['tw'] - out[0]['ts']
    out[1]['tdiff'] = out[1]['tw'] - out[1]['ts']
    return out


def backtest(r, cash_m):
    """겨울(11~4월)만 주식, 나머지는 현금. cash_m = 월 무위험수익 % 시리즈."""
    cm = pd.Series(cash_m).reindex(r.index).ffill().fillna(0.25)
    isw = pd.Series(is_winter(r.index), index=r.index)
    sw = pd.Series(np.where(isw, r, cm), index=r.index)
    trade = isw.astype(int).diff().abs().fillna(0)
    rows = [('매수후보유', r), ('겨울만보유 (비용 0)', sw),
            (f'겨울만보유 (왕복 {COST*2:.1f}%)', sw - trade * COST),
            ('여름만보유', pd.Series(np.where(~isw, r, cm), index=r.index))]
    out = []
    for nm, x in rows:
        yrs = len(x) / 12
        cum = float((1 + x / 100).prod())
        cagr = cum ** (1 / yrs) - 1
        sd = float(x.std()) * math.sqrt(12) / 100
        eq = (1 + x / 100).cumprod()
        out.append(dict(name=nm, cum=(cum - 1) * 100, cagr=cagr * 100, sd=sd * 100,
                        sharpe=cagr / sd if sd else 0.0,
                        mdd=float((eq / eq.cummax() - 1).min()) * 100,
                        eq=eq))
    return out


# ── 켈리 계절조정 ────────────────────────────────────────────────────────
def kelly_anchors(px, rf_ann, cut=None, h=6, kelly_fn=None):
    """향후 h개월 창을 '겨울 우세 / 여름 우세'로 나눠 켈리 앵커를 구한다.

    왜 승수(비율)가 아니라 Δf(가산)인가:
      f_전체 가 0 근처면(코스닥 6개월 f*=+0.14) 비율이 13.6배로 폭발한다.
      가산이면 겨울 +1.70 / 여름 −1.16 로 안정적이고, 상하한(+150%/−50%)과도 잘 맞는다.
    """
    kf = kelly_fn or (lambda v: kelly(v))
    s = pd.Series(px).dropna()
    if cut is not None: s = s.loc[:cut]
    ex = (s.pct_change(h).shift(-h) - pd.Series(rf_ann).reindex(s.index).ffill() / 100 * (h / 12)).dropna()
    wf = pd.Series([wfrac(t, h) for t in ex.index], index=ex.index)
    hi_, lo_ = wf >= 0.66, wf <= 0.34

    def blk(v):
        v = np.asarray(v, float)
        w_, l_ = v[v > 0], v[v <= 0]
        return dict(n=len(v), mu=float(v.mean()) * 100, sd=float(v.std(ddof=1)) * 100,
                    p=float(len(w_) / len(v)) * 100,
                    b=float(w_.mean() / abs(l_.mean())) if len(l_) and len(w_) else float('inf'),
                    f=float(kf(v)))

    A, W, S = blk(ex.values), blk(ex[hi_].values), blk(ex[lo_].values)
    # 겨울비중 1단위당 Δf 기울기 — 두 앵커의 평균 겨울비중 사이를 잇는 직선
    span = float(wf[hi_].mean() - wf[lo_].mean())
    slope = (W['f'] - S['f']) / span if span else 0.0
    return dict(h=h, all=A, win=W, sum=S, slope=slope, n=len(ex),
                wf_win=float(wf[hi_].mean()), wf_sum=float(wf[lo_].mean()))


def season_delta(anch, ts, shrink=SHRINK):
    """지금(ts 월말) 진입할 때의 켈리 가산조정 Δf. 겨울비중 0.5 에서 정확히 0."""
    wf_ = wfrac(ts, anch['h'])
    return dict(wf=wf_, raw=anch['slope'] * (wf_ - 0.5),
                adj=shrink * anch['slope'] * (wf_ - 0.5))


def season_now(ts):
    """오늘이 천국/지옥 중 어디인지 + 다음 전환까지 남은 일수"""
    ts = pd.Timestamp(ts)
    winter = ts.month in WMO
    # 전환일: 겨울 진입 = 11/1, 여름 진입 = 5/1
    y = ts.year
    nxt = pd.Timestamp(y, 5, 1) if winter else pd.Timestamp(y, 11, 1)
    if nxt <= ts.normalize():
        nxt = pd.Timestamp(y + 1, 5, 1) if winter else pd.Timestamp(y + 1, 11, 1)
    return dict(winter=winter, label='천국 구간 (11~4월)' if winter else '지옥 구간 (5~10월)',
                next=nxt, days=int((nxt - ts.normalize()).days),
                nextlabel='지옥 시작' if winter else '천국 시작')
