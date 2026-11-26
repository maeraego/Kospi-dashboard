"""추세추종(이평 필터) 진단 — 코스피/코스닥 일별 종가.

  python check_trend.py           단독 성과(MA20/40/60) + 구간별 + 민감도 + 켈리 레버리지
  python check_trend.py --full    레짐점수·계절성과의 결합 백테스트까지 (build_dashboard 임포트, 느림)

규칙(룩어헤드 제거): t일 종가로 신호 판정 → t일 종가 체결 → t+1일 수익부터 반영 (pos = sig.shift(1)).
비용 편도 0.05%(레버리지 L이면 L배), 현금 = CD91, 레버리지 차입금리 = CD91 (선물 보유 + 잔여현금 MMF와 동치).
한계: 배당 제외 가격지수(매수후보유가 연 1.5~2%p 불리), 코스피200 아님(종합지수로 대체).

레짐 결합: build_dashboard.analyze()의 월말 점수를 expanding 백분위로 바꿔 '다음 달 첫 거래일부터' 적용.
          레짐 가중은 전기간 IC로 정해진 것이라 결합 결과는 낙관적이다(check_season.py와 같은 한계).
계절: 11~4월 보유(달력이라 지연 불필요).
"""
import sys
import numpy as np, pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
COST = 0.0005
WMO = (11, 12, 1, 2, 3, 4)
COLS = {'KOSPI': 'KOSPI_종가', 'KOSDAQ': 'KOSDAQ_종가'}


def load(k):
    px = pd.read_parquet('krx_daily.parquet')[COLS[k]].dropna()
    cd = pd.read_parquet('ecos_daily.parquet')['CD91'].reindex(px.index).ffill().bfill() / 100
    dt = px.index.to_series().diff().dt.days.fillna(1)
    return px, px.pct_change().fillna(0), cd * dt / 365


def run(rs, rf, w, L=1.0, cost=COST, fee=0.0):
    """w: 보유비중(0~1, 이미 지연 적용된 것). 보유분은 L배 레버리지."""
    w = w.reindex(rs.index).fillna(0)
    ret = w * (L * rs - (L - 1) * rf - fee / 252) + (1 - w) * rf - w.diff().abs().fillna(0) * cost * L
    return ret


def stats(ret, rf):
    eq = (1 + ret).cumprod()
    yrs = (ret.index[-1] - ret.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = ret.std() * np.sqrt(252)
    sh = (ret - rf.reindex(ret.index)).mean() * 252 / vol
    return cagr, (eq / eq.cummax() - 1).min(), vol, sh


def ma_sig(px, N, lag=1):
    return (px > px.rolling(N).mean()).astype(float).shift(lag).fillna(0)


def kelly(rs, rf, w):
    """보유 구간 일간 레버리지의 경험 E[log] 최대화 (분포 가정 없음, 0~8배 격자)."""
    m = w.reindex(rs.index).fillna(0) > 0
    ex, r0, ww = (rs - rf)[m], rf[m], w.reindex(rs.index)[m]
    Ls = np.arange(0, 8.001, 0.05)
    ex, r0, ww = ex.values, r0.values, ww.values
    g = []
    for L in Ls:
        x = 1 + r0 + L * ww * ex
        g.append(np.log(x).sum() if (x > 0).all() else -np.inf)   # 하루라도 파산이면 −∞
    return Ls[int(np.argmax(g))]


def line(nm, ret, rf, w=None):
    c, dd, v, sh = stats(ret, rf)
    yrs = len(ret) / 252
    ex = '' if w is None else f' {w.reindex(ret.index).mean()*100:>5.0f}% {w.reindex(ret.index).diff().abs().sum()/yrs/2:>6.1f}'
    print(f'{nm:>22} {c*100:>7.2f} {dd*100:>7.1f} {v*100:>6.1f} {sh:>6.2f}{ex}')


HDR = f'{"전략":>22} {"CAGR%":>7} {"MDD%":>7} {"변동%":>6} {"샤프":>6} {"보유":>6} {"왕복/년":>6}'


def solo(k):
    px, rs, rf = load(k)
    st = px.index[62]
    print('\n' + '#' * 78 + f'\n# {k} 추세추종 단독 ({st:%Y-%m-%d}~{px.index[-1]:%Y-%m-%d})\n' + '#' * 78)
    print(HDR)
    one = pd.Series(1.0, index=rs.index)
    line('매수후보유', run(rs, rf, one)[st:], rf, one)
    for N in (20, 40, 60):
        w = ma_sig(px, N)
        line(f'MA{N}', run(rs, rf, w)[st:], rf, w)
    print('\n  민감도 CAGR/MDD: 현금이자0 | 익일종가체결 | 비용 편도0.2%')
    for N in (20, 40, 60):
        w = ma_sig(px, N)
        a = run(rs, rf * 0, w)[st:]
        b = run(rs, rf, ma_sig(px, N, lag=2))[st:]
        c = run(rs, rf, w, cost=0.002)[st:]
        print(f'  MA{N}: ' + ' | '.join(f'{stats(x, rf)[0]*100:+.1f}%/{stats(x, rf)[1]*100:.0f}%' for x in (a, b, c)))
    print('\n  구간별 CAGR/MDD')
    for s, e in (('1995', '2002'), ('2003', '2010'), ('2011', '2019'), ('2020', None), ('2011', None)):
        row = [f'{s}~{e or "현재"}']
        for nm, w in [('BH', one)] + [(f'MA{N}', ma_sig(px, N)) for N in (20, 40, 60)]:
            x = run(rs, rf, w)[st:][s:e]
            c, dd, _, _ = stats(x, rf)
            row.append(f'{nm} {c*100:+5.1f}/{dd*100:4.0f}')
        print('  ' + ' | '.join(row))
    print('\n  켈리(보유구간 일간 레버리지, 차입=CD91) 전체 / 1995~2010 / 2011~')
    for N in (20, 40, 60):
        w = ma_sig(px, N)
        Ls = [kelly(rs[st:e][s:], rf[st:e][s:], w) for s, e in ((None, None), (None, '2010'), ('2011', None))]
        lev = ' | '.join(f'L{L:.2f} {stats(run(rs, rf, w, L=L)[st:], rf)[0]*100:+.1f}%/{stats(run(rs, rf, w, L=L)[st:], rf)[1]*100:.0f}%'
                         for L in (1, 1.5, 2, Ls[0]))
        print(f'  MA{N}: L*={Ls[0]:.2f} ({Ls[1]:.2f}/{Ls[2]:.2f})  {lev}')
    print(f'  참고 매수후보유 L*={kelly(rs[st:], rf[st:], one):.2f}')


def regime_daily(k, idx):
    import build_dashboard as bd
    sc = bd.analyze(k)['sc']
    pct = sc.expanding(36).apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False).dropna()
    # 월말 M 점수 → M+1 첫 거래일부터 (해당 월말 종가 체결 → 다음 날부터 반영)
    s = pd.Series(np.nan, index=idx)
    for t, v in pct.items():
        nxt = idx[idx > t]
        if len(nxt):
            s.loc[nxt[0]] = v
    return s.ffill()


def combo(k):
    px, rs, rf = load(k)
    pct = regime_daily(k, px.index)
    st = pct.dropna().index[0]
    ma = ma_sig(px, 40)
    reg = (pct >= 0.5).astype(float)
    hot = (pct >= 0.7).astype(float)
    sea = pd.Series(px.index.month.isin(WMO).astype(float), index=px.index).shift(1).fillna(0)
    S = {
        '매수후보유': pd.Series(1.0, index=px.index),
        'MA40': ma,
        '레짐(백분위≥50)': reg,
        '계절(11~4월)': sea,
        'MA40 AND 레짐': ma * reg,
        'MA40 OR 레짐≥70': ((ma + hot) > 0).astype(float),
        'MA40 AND 계절': ma * sea,
        'MA40 OR 계절': ((ma + sea) > 0).astype(float),
        '3표 중 2표': ((ma + reg + sea) >= 2).astype(float),
        '3신호 평균비중': (ma + reg + sea) / 3,
        'MA40 비중1·이탈시레짐≥70만0.5': ma + (1 - ma) * hot * 0.5,
    }
    print('\n' + '#' * 78 + f'\n# {k} 결합 ({st:%Y-%m-%d}~{px.index[-1]:%Y-%m-%d}, 레짐 1개월 지연)\n' + '#' * 78)
    print(HDR)
    for nm, w in S.items():
        line(nm, run(rs, rf, w)[st:], rf, w)
    mid = st + (px.index[-1] - st) / 2
    print(f'\n  전반/후반 CAGR·MDD (분할 {mid:%Y-%m})  + 켈리 L*')
    for nm, w in S.items():
        a = run(rs, rf, w)[st:mid]; b = run(rs, rf, w)[mid:]
        Lk = kelly(rs[st:], rf[st:], w)
        La, Lb = kelly(rs[st:mid], rf[st:mid], w), kelly(rs[mid:], rf[mid:], w)
        h = run(rs, rf, w, L=Lk / 2)[st:]
        print(f'  {nm:>22} 전반 {stats(a, rf)[0]*100:+5.1f}/{stats(a, rf)[1]*100:4.0f} 후반 {stats(b, rf)[0]*100:+5.1f}/{stats(b, rf)[1]*100:4.0f}'
              f' | L* {Lk:.2f} ({La:.2f}/{Lb:.2f}) ½켈리 {stats(h, rf)[0]*100:+.1f}%/{stats(h, rf)[1]*100:.0f}%')
    print('\n  신호 상관(일별 보유여부): '
          f'MA40~레짐 {ma[st:].corr(reg[st:]):+.2f} · MA40~계절 {ma[st:].corr(sea[st:]):+.2f} · 레짐~계절 {reg[st:].corr(sea[st:]):+.2f}')
    print(f'  현재: MA40 {"위" if px.iloc[-1] > px.rolling(40).mean().iloc[-1] else "아래"}'
          f' (종가 {px.iloc[-1]:,.0f} vs 40일선 {px.rolling(40).mean().iloc[-1]:,.0f}) · 레짐 백분위 {pct.iloc[-1]*100:.0f}%'
          f' · 계절 {"겨울" if px.index[-1].month in WMO else "여름"}')


if __name__ == '__main__':
    for k in ('KOSPI', 'KOSDAQ'):
        solo(k)
    if '--full' in sys.argv:
        for k in ('KOSPI', 'KOSDAQ'):
            combo(k)
