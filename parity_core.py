# -*- coding: utf-8 -*-
"""
parity_core.py — 짝수해/홀수해(연도 홀짝) 효과 계산 코어

  "홀수해는 오르고 짝수해는 쉰다"는 속설을 연간 수익률로 검정하고,
  메인 대시보드가 ① 홀짝 오버레이 패널 ② 켈리 부록(최장기 데이터 재보정)에
  쓸 수치를 뽑아준다. 계절성(season_core)과 같은 취급 — 종합점수에는 넣지 않는다.

  ★ 최장기 데이터
    krx_monthly.parquet 은 1995-01 부터다. 코스피는 1980-01-04=100 기준이므로
    1981~1994 연말 종가를 아래 PRE1995 로 붙여 1982년부터 44개 연간수익을 쓴다.
    출처: 한국거래소 공표치(위키백과 '코스피' 연도별 종가표, Record Bank 교차확인).
    1980년 연말 종가는 공식 자료가 없어 넣지 않았다(1981년 수익은 계산 불가).
    코스닥은 1996-07 출범이라 1997년부터(29개).

  ★ 연간수익은 서로 겹치지 않는다 → 독립 표본
    메인 켈리 표는 월별 12개월 수익(중첩)이라 국면당 독립 표본이 3개 안팎이다.
    연간수익 44개는 진짜 44개라 승률 표준오차가 ±7%p 수준으로 작다.
    그래서 '국면 승률을 장기 기저율 쪽으로 수축'하는 재보정의 사전분포로 쓴다.

  ★ scipy 금지 (클라우드는 pandas·numpy·pyarrow 만) — t검정은 season_core 것을 쓴다.
"""
import numpy as np
import pandas as pd

try:
    from season_core import welch, t_p, trim_mean, WMO, SMO
except Exception:                         # season_core 가 없어도 홀짝 패널은 살아야 한다
    WMO, SMO = (11, 12, 1, 2, 3, 4), (5, 6, 7, 8, 9, 10)

    def welch(a, b):
        return float('nan'), float('nan')

    def t_p(t, d):
        return float('nan')

    def trim_mean(a, frac=0.1):
        a = np.sort(np.asarray(a, float)); k = int(len(a) * frac)
        return float(a[k:len(a) - k].mean()) if len(a) > 2 * k else float('nan')

SHRINK = 0.5      # 홀짝 프리미엄 축소계수 — 계절·국면프리미엄과 같은 관례(절반만 반영)

# 코스피 연말 종가 1981~1994 (1980-01-04 = 100)
PRE1995 = {1981: 131.30, 1982: 128.99, 1983: 121.21, 1984: 142.46, 1985: 163.37,
           1986: 272.61, 1987: 525.11, 1988: 907.20, 1989: 909.72, 1990: 696.11,
           1991: 610.92, 1992: 678.44, 1993: 866.18, 1994: 1027.37}

SUBP = [(1982, 1994), (1995, 2009), (2010, 2099)]


def annual(px, idx, cut):
    """완결된 연도의 연간수익(소수) + 올해 YTD. cut = 마지막 완결 월말."""
    s = pd.Series(px).dropna()
    s = s.loc[:cut]
    ye = s.groupby(s.index.year).last()
    last_m = s.groupby(s.index.year).apply(lambda x: x.index[-1].month)
    full = ye[last_m == 12]
    if idx == 'KOSPI':
        pre = pd.Series(PRE1995)
        full = pd.concat([pre[pre.index < full.index.min()], full])
    # 첫 해가 부분연도(코스닥 1996: 7~12월)면 그 해 수익은 버린다 → pct_change 가 알아서 빠짐
    r = full.pct_change().dropna()
    r.index = r.index.astype(int)
    ytd = None
    yr_now = int(s.index[-1].year)
    if yr_now not in r.index and (yr_now - 1) in full.index:
        ytd = dict(year=yr_now, r=float(s.iloc[-1] / full.loc[yr_now - 1] - 1),
                   asof=s.index[-1], parity='홀수' if yr_now % 2 else '짝수')
    return r, ytd


def kelly_simple(v):
    v = np.asarray(v, float)
    w, l = v[v > 0], v[v <= 0]
    p = len(w) / len(v) if len(v) else float('nan')
    aw = float(w.mean()) if len(w) else 0.0
    al = float(abs(l.mean())) if len(l) else 0.0
    if aw > 0 and al > 0:
        b = aw / al; f = p - (1 - p) / b
    elif al == 0:
        b, f = float('inf'), 1.5
    else:
        b, f = 0.0, -0.5
    return p, aw, al, b, f


def blk(v, kelly_fn):
    v = np.asarray(v, float)
    p, aw, al, b, f = kelly_simple(v)
    return dict(n=len(v), mu=float(v.mean()), med=float(np.median(v)),
                sd=float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                geo=float(np.exp(np.log1p(v).mean()) - 1), tm=trim_mean(v, 0.1),
                p=p, aw=aw, al=al, b=b, f=f, fc=float(kelly_fn(v)),
                best=float(v.max()), worst=float(v.min()))


def parity_stats(r, kelly_fn):
    ev, od = r[r.index % 2 == 0], r[r.index % 2 == 1]
    t, p = welch(od.values, ev.values)
    # 짝수해 → 바로 다음 홀수해 쌍에서 홀수가 이긴 횟수
    pairs = [(y, y + 1) for y in ev.index if (y + 1) in od.index]
    beat = sum(od[y1] > ev[y0] for y0, y1 in pairs)
    sub = []
    for a, b in SUBP:
        x = r.loc[a:b]
        if len(x) < 4:
            continue
        e_, o_ = x[x.index % 2 == 0], x[x.index % 2 == 1]
        tt, pp = welch(o_.values, e_.values)
        sub.append(dict(a=int(x.index.min()), b=int(x.index.max()),
                        e=float(e_.mean()), o=float(o_.mean()),
                        ew=float((e_ > 0).mean()), ow=float((o_ > 0).mean()),
                        diff=float(o_.mean() - e_.mean()), t=tt, p=pp))
    return dict(all=blk(r.values, kelly_fn), even=blk(ev.values, kelly_fn),
                odd=blk(od.values, kelly_fn), t=t, p=p, beat=int(beat), npair=len(pairs),
                sub=sub, span=(int(r.index.min()), int(r.index.max())), r=r)


def parity_season(px, cut):
    """홀짝 × 계절 2×2 — 월평균 수익(%)·승률. 월별 데이터가 있는 1995년부터."""
    s = pd.Series(px).dropna().loc[:cut]
    m = s.pct_change().dropna() * 100
    yr, mo = m.index.year, m.index.month
    out = {}
    for par, pk in ((1, 'odd'), (0, 'even')):
        for mos, sk in ((WMO, 'w'), (SMO, 's')):
            # 달력 연도 기준(그 해의 1~4·11~12월 / 5~10월). 겨울을 시즌 단위로 묶지 않는다.
            x = m[(yr % 2 == par) & np.isin(mo, mos)]
            out[pk + sk] = dict(n=len(x), mean=float(x.mean()), win=float((x > 0).mean() * 100),
                                ann=float((np.prod(1 + x / 100) ** (12 / len(x)) - 1) * 100) if len(x) else float('nan'))
    out['span'] = (int(m.index.min().year), int(m.index.max().year))
    return out


def odd_share(ent, h=12):
    """ent(월말)에 진입했을 때 향후 h개월 중 홀수해에 속하는 몫"""
    ms = pd.date_range(pd.Timestamp(ent) + pd.offsets.MonthEnd(1), periods=h, freq='ME')
    return float(np.mean([d.year % 2 == 1 for d in ms]))


def parity_delta(ps, share_odd, shrink=SHRINK):
    """켈리 가산조정 Δf — 단순켈리 기준(메인 큰 숫자가 단순켈리라서).
       향후 12개월의 홀/짝 몫으로 두 앵커를 섞고 전체 대비 차이의 절반만 반영."""
    fa, fo, fe = ps['all']['f'], ps['odd']['f'], ps['even']['f']
    raw = share_odd * (fo - fa) + (1 - share_odd) * (fe - fa)
    return dict(share=share_odd, raw=raw, adj=shrink * raw, fo=fo, fe=fe, fa=fa)
