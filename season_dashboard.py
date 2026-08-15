# -*- coding: utf-8 -*-
"""
season_dashboard.py — 계절성(핼러윈 효과) 전용 대시보드

  "코스피·코스닥은 5~10월 지옥, 11~4월 천국"이 사실인지 자체 데이터로 검증해
  자체완결 HTML 한 장으로 만든다. 메인 대시보드(build_dashboard.py)와는 별개이며,
  계산은 season_core.py 를 공유한다.

사용법:  C:/python312/python.exe season_dashboard.py
입력:    krx_monthly.parquet, krx_daily.parquet, ecos_monthly.parquet
출력:    season_dashboard.html
"""
import os, sys, math
import numpy as np, pandas as pd
import season_core as SC

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

GRN, RED, MUT, TXT = '#3fb37f', '#e5484d', '#8b98ab', '#e6edf3'
IDX = [('KOSPI', '코스피'), ('KOSDAQ', '코스닥')]


def load():
    m = pd.read_parquet(os.path.join(HERE, 'krx_monthly.parquet'))
    m.index = pd.to_datetime(m.index)
    d = pd.read_parquet(os.path.join(HERE, 'krx_daily.parquet'))
    d.index = pd.to_datetime(d.index)
    e = pd.read_parquet(os.path.join(HERE, 'ecos_monthly.parquet'))
    e.index = pd.to_datetime(e.index)
    return m, d, e


def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def pcls(p):
    """유의성 표시 — 표본이 30개짜리 월별 검정이라 별표를 남발하지 않도록 3단계만"""
    if p != p: return '', ''
    if p < 0.01: return 'sig3', '**'
    if p < 0.05: return 'sig2', '*'
    if p < 0.10: return 'sig1', '†'
    return '', ''


# ── SVG ─────────────────────────────────────────────────────────────────
def nice_ticks(lo, hi, target=5):
    """1·2·2.5·5·10 계열로 떨어지는 눈금 — linspace 를 그대로 쓰면 '+94%' 같은 축이 나온다"""
    rng = (hi - lo) or 1
    raw = rng / max(target - 1, 1)
    mag = 10.0 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)
    t0 = math.ceil(lo / step) * step
    return [t0 + i * step for i in range(int((hi - t0) / step) + 1)]


def svg_month_bars(tbl, w=900, h=230):
    """월별 평균수익 막대 — 겨울 초록 / 여름 빨강"""
    padL, padR, padT, padB = 44, 14, 16, 30
    vals = [r['mean'] for r in tbl]
    lo, hi = min(min(vals), 0), max(max(vals), 0)
    rng = (hi - lo) or 1
    lo -= rng * .16; hi += rng * .20; rng = hi - lo
    Y = lambda v: padT + (hi - v) / rng * (h - padT - padB)
    bw = (w - padL - padR) / 12
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart">']
    for gv in nice_ticks(lo, hi):
        out.append(f'<line x1="{padL}" x2="{w-padR}" y1="{Y(gv):.1f}" y2="{Y(gv):.1f}" stroke="#1e2838"/>'
                   f'<text x="{padL-6}" y="{Y(gv)+3.5:.1f}" text-anchor="end" class="ax">{gv:+.0f}%</text>')
    out.append(f'<line x1="{padL}" x2="{w-padR}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#3a465a" stroke-width="1.4"/>')
    for i, r in enumerate(tbl):
        x = padL + i * bw + bw * .18
        bwid = bw * .64
        c = GRN if r['winter'] else RED
        y0, y1 = Y(max(r['mean'], 0)), Y(min(r['mean'], 0))
        out.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bwid:.1f}" height="{max(y1-y0,0.7):.1f}" '
                   f'fill="{c}" opacity="{.88 if r["p"]<.10 else .5}" rx="2"/>')
        ty = y0 - 5 if r['mean'] >= 0 else y1 + 12
        out.append(f'<text x="{x+bwid/2:.1f}" y="{ty:.1f}" text-anchor="middle" class="bl" fill="{c}">'
                   f'{r["mean"]:+.1f}</text>')
        out.append(f'<text x="{x+bwid/2:.1f}" y="{h-9}" text-anchor="middle" class="ax">{r["m"]}</text>')
    out.append('</svg>')
    return ''.join(out)


def svg_year_bars(sy, w=900, h=260):
    """연도별 겨울시즌 vs 여름시즌 — 같은 해를 나란히"""
    padL, padR, padT, padB = 44, 14, 14, 34
    allv = list(sy['w']) + list(sy['s'])
    lo, hi = min(min(allv), 0), max(max(allv), 0)
    rng = (hi - lo) or 1; lo -= rng * .06; hi += rng * .06; rng = hi - lo
    Y = lambda v: padT + (hi - v) / rng * (h - padT - padB)
    n = len(sy['years']); gw = (w - padL - padR) / n
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart">']
    for gv in nice_ticks(lo, hi):
        out.append(f'<line x1="{padL}" x2="{w-padR}" y1="{Y(gv):.1f}" y2="{Y(gv):.1f}" stroke="#1e2838"/>'
                   f'<text x="{padL-6}" y="{Y(gv)+3.5:.1f}" text-anchor="end" class="ax">{gv:+.0f}%</text>')
    out.append(f'<line x1="{padL}" x2="{w-padR}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#3a465a" stroke-width="1.3"/>')
    for i, y in enumerate(sy['years']):
        x = padL + i * gw
        for j, (v, c) in enumerate(((sy['w'][i], '#4a9fd4'), (sy['s'][i], '#d4884a'))):
            bx = x + gw * (.12 + j * .40); bwid = gw * .36
            y0, y1 = Y(max(v, 0)), Y(min(v, 0))
            out.append(f'<rect x="{bx:.1f}" y="{y0:.1f}" width="{bwid:.1f}" '
                       f'height="{max(y1-y0,0.6):.1f}" fill="{c}" rx="1.5"><title>{y} '
                       f'{"겨울" if j==0 else "여름"} {v:+.1f}%</title></rect>')
        if i % 2 == 0 or n < 20:
            out.append(f'<text x="{x+gw/2:.1f}" y="{h-8}" text-anchor="middle" class="ax">'
                       f'{str(y)[2:]}</text>')
    out.append('</svg>')
    return ''.join(out)


def svg_equity(bt, dates, w=900, h=250):
    """누적곡선(로그) — 매수후보유 / 겨울만 / 여름만"""
    padL, padR, padT, padB = 52, 14, 14, 26
    series = [(bt[0], '#8b98ab', '매수후보유'), (bt[2], GRN, '겨울만보유'), (bt[3], RED, '여름만보유')]
    allv = np.concatenate([np.log10(np.maximum(s[0]['eq'].values, 1e-3)) for s in series])
    lo, hi = float(allv.min()), float(allv.max())
    rng = (hi - lo) or 1; lo -= rng * .05; hi += rng * .05; rng = hi - lo
    Y = lambda v: padT + (hi - np.log10(max(v, 1e-3))) / rng * (h - padT - padB)
    N = len(dates); X = lambda i: padL + i / max(N - 1, 1) * (w - padL - padR)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart">']
    for e10 in range(int(np.floor(lo)), int(np.ceil(hi)) + 1):
        gv = 10.0 ** e10
        if not (lo <= e10 <= hi): continue
        out.append(f'<line x1="{padL}" x2="{w-padR}" y1="{Y(gv):.1f}" y2="{Y(gv):.1f}" stroke="#1e2838"/>'
                   f'<text x="{padL-6}" y="{Y(gv)+3.5:.1f}" text-anchor="end" class="ax">'
                   f'{("x%g"%gv) if gv>=1 else ("x%.2f"%gv)}</text>')
    for st, c, lab in series:
        pts = ' '.join(f'{X(i):.1f},{Y(v):.1f}' for i, v in enumerate(st['eq'].values))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.7" '
                   f'stroke-linejoin="round" opacity=".95"/>')
    step = max(N // 8, 1)
    for i in range(0, N, step):
        out.append(f'<text x="{X(i):.1f}" y="{h-7}" text-anchor="middle" class="ax">{dates[i][:4]}</text>')
    out.append('</svg>')
    lg = ' '.join(f'<span class="lg"><i style="background:{c}"></i>{lab}</span>' for _, c, lab in series)
    return ''.join(out) + f'<div class="lgs">{lg}</div>'


# ── 섹션 ─────────────────────────────────────────────────────────────────
def block(key, label, r, cut, cash, px):
    tbl = SC.month_table(r)
    ws = SC.winter_vs_summer(r)
    sy = SC.season_years(r)
    sp = SC.subperiods(r, cut)
    rb = SC.robustness(r)
    bt = SC.backtest(r, cash)
    alt = {'4~10월': SC.split_stats(r, (4, 5, 6, 7, 8, 9, 10)),
           '11~3월': SC.split_stats(r, (11, 12, 1, 2, 3))}

    # 월별 표
    mrows = ''
    for t in tbl:
        cl, star = pcls(t['p'])
        c = GRN if t['mean'] >= 0 else RED
        mrows += (f'<tr class="{"wtr" if t["winter"] else ""}">'
                  f'<td class="mn">{t["name"]}<span class="tag">{"천국" if t["winter"] else "지옥"}</span></td>'
                  f'<td class="num" style="color:{c};font-weight:650">{t["mean"]:+.2f}<span class="st">{star}</span></td>'
                  f'<td class="num">{t["med"]:+.2f}</td>'
                  f'<td class="num">{t["win"]:.1f}</td><td class="num dim">{t["sd"]:.2f}</td>'
                  f'<td class="num dim">{t["t"]:+.2f}</td><td class="num {cl}">{t["p"]:.3f}</td>'
                  f'<td class="num dim">{t["mx"]:+.1f}</td><td class="num dim">{t["mn"]:+.1f}</td>'
                  f'<td class="num dim">{t["n"]}</td></tr>')

    # 구간 비교 표
    def srow(nm, s, hl=''):
        c = GRN if s['ann'] >= 0 else RED
        return (f'<tr{hl}><td>{nm}</td><td class="num">{s["n"]}</td>'
                f'<td class="num" style="color:{GRN if s["mean"]>=0 else RED}">{s["mean"]:+.2f}</td>'
                f'<td class="num">{s["med"]:+.2f}</td><td class="num">{s["win"]:.1f}</td>'
                f'<td class="num dim">{s["sd"]:.2f}</td><td class="num">{s["cum"]:+,.0f}</td>'
                f'<td class="num" style="color:{c};font-weight:650">{s["ann"]:+.2f}</td></tr>')
    crows = (srow('11~4월 <b class="gw">천국</b>', ws['w'], ' class="hi"')
             + srow('5~10월 <b class="rw">지옥</b>', ws['s'], ' class="hi"')
             + srow('<span class="dim">4~10월 (대조)</span>', alt['4~10월'])
             + srow('<span class="dim">11~3월 (대조)</span>', alt['11~3월']))

    # 하위기간
    prows = ''
    for p in sp:
        cl, star = pcls(p['p'])
        prows += (f'<tr><td>{p["name"]}</td><td class="num dim">{p["n"]}</td>'
                  f'<td class="num" style="color:{GRN}">{p["w"]:+.2f}</td>'
                  f'<td class="num" style="color:{RED if p["s"]<0 else MUT}">{p["s"]:+.2f}</td>'
                  f'<td class="num" style="font-weight:650">{p["diff"]:+.2f}</td>'
                  f'<td class="num dim">{p["t"]:+.2f}</td><td class="num {cl}">{p["p"]:.3f}{star}</td></tr>')

    # 강건성
    rrows = ''
    for x in rb:
        cl, star = pcls(x['p'])
        rrows += (f'<tr><td>{x["name"]}</td><td class="num dim">{x["n"]}</td>'
                  f'<td class="num">{x["w"]:+.2f}</td><td class="num">{x["s"]:+.2f}</td>'
                  f'<td class="num" style="font-weight:650">{x["diff"]:+.2f}</td>'
                  f'<td class="num {cl}">{x["p"]:.3f}{star}</td>'
                  f'<td class="num dim">{x["tw"]:+.2f}</td><td class="num dim">{x["ts"]:+.2f}</td>'
                  f'<td class="num">{x["tdiff"]:+.2f}</td></tr>')

    # 백테스트
    brows = ''
    for i, b in enumerate(bt):
        hl = ' class="hi"' if '왕복' in b['name'] else ''
        brows += (f'<tr{hl}><td>{b["name"]}</td>'
                  f'<td class="num">{b["cum"]:+,.0f}</td>'
                  f'<td class="num" style="color:{GRN if b["cagr"]>=0 else RED};font-weight:650">{b["cagr"]:+.2f}</td>'
                  f'<td class="num dim">{b["sd"]:.1f}</td><td class="num">{b["sharpe"]:.2f}</td>'
                  f'<td class="num" style="color:{RED}">{b["mdd"]:.1f}</td></tr>')

    verdict = ('사실' if ws['p'] < 0.05 else '방향은 맞지만 통계적으로는 약함')
    vc = GRN if ws['p'] < 0.05 else '#e8a33d'
    dates = [d.strftime('%Y-%m') for d in r.index]

    return f'''
<div class="ix" id="ix-{key}">
  <div class="sec-head"><div class="sec-t">{label}<span class="sec-px">{px:,.2f}</span></div>
    <div class="verd" style="border-color:{vc};color:{vc}">판정: {verdict}</div></div>

  <div class="cards">
    <div class="kpi"><div class="kl">11~4월 «천국» 연율</div>
      <div class="kv" style="color:{GRN}">{ws['w']['ann']:+.1f}%</div>
      <div class="kc">월평균 {ws['w']['mean']:+.2f}% · 승률 {ws['w']['win']:.0f}% · {ws['w']['n']}개월</div></div>
    <div class="kpi"><div class="kl">5~10월 «지옥» 연율</div>
      <div class="kv" style="color:{RED}">{ws['s']['ann']:+.1f}%</div>
      <div class="kc">월평균 {ws['s']['mean']:+.2f}% · 승률 {ws['s']['win']:.0f}% · {ws['s']['n']}개월</div></div>
    <div class="kpi"><div class="kl">격차 · 유의성</div>
      <div class="kv">{ws['diff']:+.2f}<span class="ku">%p/월</span></div>
      <div class="kc">Welch t={ws['t']:.2f} · p={ws['p']:.4f}</div></div>
    <div class="kpi"><div class="kl">겨울이 이긴 해</div>
      <div class="kv">{sy['beat']}<span class="ku">/{sy['nyr']}</span></div>
      <div class="kc">{sy['beat']/sy['nyr']*100:.0f}% · 대응표본 p={sy['p']:.4f}</div></div>
  </div>

  <div class="card">
    <h2>1. 월별 수익률 <span class="h2-sub">{r.index[0]:%Y-%m} ~ {r.index[-1]:%Y-%m} · n={len(r)}개월 · 초록=천국(11~4월), 빨강=지옥(5~10월)</span></h2>
    {svg_month_bars(tbl)}
    <div class="tw"><table class="raw">
      <thead><tr><th>월</th><th class="num">평균%</th><th class="num">중앙%</th><th class="num">승률%</th>
      <th class="num">σ</th><th class="num">t</th><th class="num">p</th><th class="num">최고%</th>
      <th class="num">최저%</th><th class="num">n</th></tr></thead>
      <tbody>{mrows}</tbody>
      <tfoot><tr><td>전체</td><td class="num">{r.mean():+.2f}</td><td class="num">{r.median():+.2f}</td>
      <td class="num">{(r>0).mean()*100:.1f}</td><td class="num">{r.std():.2f}</td>
      <td colspan="4"></td><td class="num">{len(r)}</td></tr></tfoot></table></div>
    <p class="note">월 하나하나는 표본이 30개뿐이라 t검정이 거의 통과하지 못합니다
      (<b>* p&lt;0.05, ** p&lt;0.01, † p&lt;0.10</b>). 계절성은 <b>6개월씩 묶어야</b> 신호가 드러납니다.</p>
  </div>

  <div class="card">
    <h2>2. 구간 비교 <span class="h2-sub">누적·연율은 해당 월에만 투자했을 때</span></h2>
    <div class="tw"><table class="raw">
      <thead><tr><th>구간</th><th class="num">개월</th><th class="num">월평균%</th><th class="num">중앙%</th>
      <th class="num">승률%</th><th class="num">σ</th><th class="num">누적%</th><th class="num">연율%</th></tr></thead>
      <tbody>{crows}</tbody></table></div>
    <p class="note"><b>"4~10월 천국"은 성립하지 않습니다.</b> 4월 한 달만 좋고 5~10월이 전부 나빠서,
      4~10월을 통으로 묶으면 연율 {alt['4~10월']['ann']:+.1f}%에 그칩니다.
      올바른 짝은 <b>11~4월 천국 / 5~10월 지옥</b>입니다.</p>
  </div>

  <div class="card">
    <h2>3. 시즌별 연도 <span class="h2-sub">겨울=전년 11월~당년 4월 · 여름=당년 5~10월 · 6개월이 다 찬 시즌만</span></h2>
    {svg_year_bars(sy)}
    <div class="lgs"><span class="lg"><i style="background:#4a9fd4"></i>겨울(11~4월)</span>
      <span class="lg"><i style="background:#d4884a"></i>여름(5~10월)</span></div>
    <div class="tw"><table class="raw">
      <thead><tr><th>지표</th><th class="num">겨울</th><th class="num">여름</th><th class="num">차이</th></tr></thead>
      <tbody>
      <tr><td>시즌 평균</td><td class="num" style="color:{GRN}">{sy['wmean']:+.2f}%</td>
        <td class="num" style="color:{RED}">{sy['smean']:+.2f}%</td>
        <td class="num" style="font-weight:650">{sy['wmean']-sy['smean']:+.2f}%p</td></tr>
      <tr><td>시즌 중앙값</td><td class="num">{sy['wmed']:+.2f}%</td><td class="num">{sy['smed']:+.2f}%</td>
        <td class="num">{sy['wmed']-sy['smed']:+.2f}%p</td></tr>
      <tr><td>플러스로 끝난 비율</td><td class="num">{sy['wpos']:.1f}%</td><td class="num">{sy['spos']:.1f}%</td>
        <td class="num">{sy['wpos']-sy['spos']:+.1f}%p</td></tr>
      <tr><td>대응표본 t검정</td><td colspan="3" class="num">t={sy['t']:.2f} · p={sy['p']:.4f}
        <span class="dim">(같은 해의 겨울·여름은 짝지어진 관측)</span></td></tr>
      </tbody></table></div>
  </div>

  <div class="card">
    <h2>4. 안정성 — 시대가 바뀌어도 남는가 <span class="h2-sub">월평균 %, Welch t검정</span></h2>
    <div class="tw"><table class="raw">
      <thead><tr><th>기간</th><th class="num">n</th><th class="num">겨울%</th><th class="num">여름%</th>
      <th class="num">차이%p</th><th class="num">t</th><th class="num">p</th></tr></thead>
      <tbody>{prows}</tbody></table></div>
    <h2 style="margin-top:18px">5. 강건성 — 위기 몇 번이 만든 착시인가</h2>
    <div class="tw"><table class="raw">
      <thead><tr><th>표본</th><th class="num">n</th><th class="num">겨울%</th><th class="num">여름%</th>
      <th class="num">차이%p</th><th class="num">p</th><th class="num">절사겨울</th><th class="num">절사여름</th>
      <th class="num">절사차이</th></tr></thead>
      <tbody>{rrows}</tbody></table></div>
    <p class="note">여름에 몰린 대형 급락(IMF 97/7~98/12 · 닷컴 2000 · 금융위기 08/1~09/3 · 코로나 20/2~20/4)을
      <b>전부 빼도</b> 격차가 남고, 상하 10%를 잘라낸 절사평균에서도 남습니다
      (절사차이 {rb[0]['tdiff']:+.2f}%p). 꼬리 몇 개가 만든 착시가 아닙니다.</p>
  </div>

  <div class="card">
    <h2>6. 백테스트 <span class="h2-sub">11~4월만 주식, 나머지는 현금(CD91) · 왕복 0.3% 비용 반영판 강조</span></h2>
    {svg_equity(bt, dates)}
    <div class="tw"><table class="raw">
      <thead><tr><th>전략</th><th class="num">누적%</th><th class="num">CAGR%</th><th class="num">연변동%</th>
      <th class="num">샤프</th><th class="num">MDD%</th></tr></thead>
      <tbody>{brows}</tbody></table></div>
    <p class="note">세로축은 로그입니다. 시장에 절반만 머물면서 CAGR은
      <b>{bt[2]['cagr']-bt[0]['cagr']:+.1f}%p</b> 높고 최대낙폭은
      <b>{abs(bt[0]['mdd']-bt[2]['mdd']):.1f}%p</b> 얕습니다.
      배당·세금은 반영하지 않았습니다(가격지수 기준).</p>
  </div>
</div>'''


def main():
    m, d, e = load()
    cut = SC.last_complete_month(d.index)
    cash = e['CD91'] / 12
    today = pd.Timestamp.today()
    now = SC.season_now(today)
    # 겨울비중은 '이번 달 말에 진입하면 향후 6개월'을 기준으로 본다(통계 절단월 cut 이 아니라).
    ent = today.to_period('M').to_timestamp('M')

    blocks, tabs = '', ''
    for i, (k, lab) in enumerate(IDX):
        r = SC.monthly_returns(m[f'{k}_종가'], cut)
        px = float(pd.Series(d[f'{k}_종가']).dropna().iloc[-1])
        blocks += block(k, lab, r, cut, cash.reindex(r.index).ffill(), px)
        tabs += (f'<button class="tab{" on" if i==0 else ""}" data-ix="{k}" '
                 f'onclick="pick(\'{k}\')">{lab}</button>')

    nowcls = 'ok' if now['winter'] else 'bad'
    asof = pd.Timestamp(d.index.max())

    html = HEAD + f'''<div class="wrap">
<div class="top">
  <div class="t">계절성 검증 — 5~10월 지옥 / 11~4월 천국<small>핼러윈 효과가 코스피·코스닥에서 실제로 작동하는지,
    보유 데이터(1995~)로 검정합니다 · 기준 {asof:%Y-%m-%d} · 통계는 {cut:%Y-%m}까지의 완결월만 사용</small></div>
  <div class="topbtns">
    <div class="dbadge {nowcls}"><b>지금은 {now['label']}</b></div>
    <a class="btn" id="mainLink" href="index.html">국면 대시보드 →</a>
  </div>
</div>

<div class="card lead">
  <div class="ld-h">지금 위치</div>
  <div class="ld-b">
    <div><span class="ld-k">현재 구간</span><span class="ld-v {nowcls}">{now['label']}</span></div>
    <div><span class="ld-k">{now['nextlabel']}까지</span><span class="ld-v">{now['days']}일
      <span class="dim">({now['next']:%Y-%m-%d})</span></span></div>
    <div><span class="ld-k">이번 달 말 진입 시 향후 6개월 겨울비중</span>
      <span class="ld-v">{SC.wfrac(ent, 6)*100:.0f}%</span></div>
  </div>
  <p class="note" style="margin-bottom:0">이 대시보드는 <b>달력만 보는</b> 지표입니다. 밸류·금리·수급을 전혀 쓰지 않습니다.
    실제 판단은 <a href="index.html">국면 대시보드</a>의 종합점수와 <b>함께</b> 보십시오 —
    두 축의 상관은 0.02~0.04로 사실상 독립이라 서로를 대체하지 않습니다.</p>
</div>

<div class="tabs">{tabs}</div>
{blocks}

<div class="card">
  <h2>한계와 주의</h2>
  <ul class="lim">
    <li><b>코스피는 최근 들어 약합니다.</b> 부호는 10개 하위기간 전부 양수로 한 번도 뒤집힌 적이 없지만,
      코스피의 최근 10년 p값은 0.25로 유의하지 않습니다. 강하게 살아있는 쪽은 <b>코스닥</b>입니다
      (최근 10년 p=0.007, 최근 5년 p=0.036). 개인 수급 비중이 큰 시장일수록 계절 패턴이 뚜렷합니다.</li>
    <li><b>바로 직전 두 시즌이 정반대였습니다.</b> 2025년 여름 코스피 +60.7% / 코스닥 +25.5% —
      겨울만 보유했다면 이 구간을 통째로 놓쳤습니다. 계절성은 평균의 이야기이지 매년의 약속이 아닙니다.</li>
    <li><b>유명해진 아노말리는 소멸할 수 있습니다.</b> 핼러윈 효과는 전 세계적으로 알려져 있어
      차익거래로 희석될 여지가 있습니다. 코스피의 유의성 약화가 그 신호일 수 있습니다.</li>
    <li><b>가격지수 기준입니다.</b> 배당(4월 전후 배당락)·세금·거래비용 중 거래비용만 반영했습니다.
      총수익 기준으로는 겨울 우위가 다소 축소됩니다.</li>
    <li><b>12개월 지평에서는 계절성이 사라집니다.</b> 어느 달에 시작하든 12개월 창은 12개 달을 전부 담기
      때문입니다(진입월별 12개월 수익 차이 p=0.76·0.93). 그래서 국면 대시보드의 12개월 예측모델에는
      계절 신호를 <b>넣지 않았고</b>, 대신 6개월 진입 타이밍 조정으로만 씁니다.</li>
  </ul>
  <p class="note dis">과거 통계에 근거한 계절 패턴 분석이며 투자 권유가 아닙니다.
    과거 30년의 규칙성이 앞으로도 유지된다는 보장은 없습니다.</p>
</div>
</div>
<script>
// 메인 대시보드 파일명이 로컬(dashboard.html)과 웹(index.html)에서 다르다.
// 이 파일이 season_dashboard.html 이면 로컬로 판단해 링크를 바꾼다.
(function(){{
  const f=location.pathname.split('/').pop();
  if(f==='season_dashboard.html'){{
    document.querySelectorAll('a[href="index.html"]').forEach(function(a){{a.href='dashboard.html';}});
  }}
}})();
function pick(k){{
  document.querySelectorAll('.ix').forEach(function(el){{
    el.style.display = (el.id === 'ix-'+k) ? 'block' : 'none';
  }});
  document.querySelectorAll('.tab').forEach(function(b){{
    b.classList.toggle('on', b.dataset.ix === k);
  }});
}}
pick('KOSPI');
</script>
</body></html>'''

    out = os.path.join(HERE, 'season_dashboard.html')
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    for k, lab in IDX:
        r = SC.monthly_returns(m[f'{k}_종가'], cut)
        ws = SC.winter_vs_summer(r)
        print(f"{lab}: 겨울 {ws['w']['ann']:+.1f}%/년 · 여름 {ws['s']['ann']:+.1f}%/년 · p={ws['p']:.4f}")
    print(f"지금은 {now['label']} · {now['nextlabel']}까지 {now['days']}일")
    print('생성 완료 → season_dashboard.html')


HEAD = '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>계절성 검증 — 5~10월 지옥 / 11~4월 천국</title>
<style>
:root{--bg:#0e1420;--panel:#161d2b;--panel2:#1b2333;--line:#26324a;--tx:#e6edf3;--mut:#8b98ab;
  --mono:ui-monospace,"SF Mono","Cascadia Code",Consolas,monospace;}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#182236 0%,var(--bg) 55%);
  color:var(--tx);font-family:system-ui,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1060px;margin:0 auto;padding:30px 22px 60px}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;flex-wrap:wrap;
  border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:22px}
.top .t{font-size:20px;font-weight:650}
.top .t small{display:block;color:var(--mut);font-weight:400;font-size:12.5px;margin-top:3px;max-width:640px;line-height:1.55}
.topbtns{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.dbadge{display:flex;align-items:center;gap:5px;font-size:11.5px;border-radius:8px;padding:6px 10px;
  border:1px solid;font-family:var(--mono)}
.dbadge.ok{color:#3fb37f;border-color:#1e4d3a;background:#0d1f18}
.dbadge.bad{color:#e5484d;border-color:#5a2326;background:#210f10}
.btn{background:#1b2333;color:#cbd5e1;border:1px solid var(--line);border-radius:8px;padding:6px 12px;
  font-size:12px;cursor:pointer;text-decoration:none;display:inline-block}
.btn:hover{background:#232d42}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:16px}
.card h2{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--mut);margin:0 0 14px;font-weight:600}
.h2-sub{text-transform:none;letter-spacing:0;color:#5b6678;font-size:10.5px;font-weight:400;margin-left:6px}
.lead .ld-h{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--mut);margin-bottom:12px;font-weight:600}
.ld-b{display:flex;gap:28px;flex-wrap:wrap;margin-bottom:12px}
.ld-k{display:block;font-size:11px;color:var(--mut);margin-bottom:3px}
.ld-v{font-family:var(--mono);font-size:16px;font-weight:600}
.ld-v.ok{color:#3fb37f}.ld-v.bad{color:#e5484d}
.tabs{display:flex;gap:8px;margin-bottom:14px}
.tab{background:#131b2a;color:#8b98ab;border:1px solid var(--line);border-radius:9px;padding:8px 20px;
  font-size:14px;font-weight:600;cursor:pointer}
.tab.on{background:#22304a;color:#e6edf3;border-color:#3a4d70}
.sec-head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:10px;gap:10px;flex-wrap:wrap}
.sec-t{font-size:22px;font-weight:700}
.sec-px{font-family:var(--mono);font-size:15px;color:var(--mut);margin-left:8px}
.verd{font-size:12.5px;font-weight:650;border:1px solid;border-radius:8px;padding:5px 12px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}
@media(max-width:820px){.cards{grid-template-columns:repeat(2,1fr)}}
.kpi{background:#131b2a;border:1px solid var(--line);border-radius:11px;padding:11px 13px}
.kl{font-size:10.5px;color:var(--mut);margin-bottom:5px}
.kv{font-family:var(--mono);font-size:23px;font-weight:650;line-height:1.1}
.ku{font-size:12px;color:var(--mut);font-weight:400;margin-left:2px}
.kc{font-size:10.5px;color:#5b6678;margin-top:5px;line-height:1.5}
.chart{width:100%;height:auto;display:block;margin-bottom:6px}
.chart .ax{font-family:var(--mono);font-size:9.5px;fill:#5b6678}
.chart .bl{font-family:var(--mono);font-size:9.5px;font-weight:600}
.lgs{display:flex;gap:14px;justify-content:center;margin:2px 0 12px;flex-wrap:wrap}
.lg{font-size:11px;color:var(--mut);display:inline-flex;align-items:center;gap:5px}
.lg i{width:11px;height:3px;border-radius:2px;display:inline-block}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.raw{width:100%;border-collapse:collapse;font-size:12px}
table.raw th{background:#131b2a;color:#8b98ab;font-weight:600;text-align:left;padding:7px 9px;
  border-bottom:1px solid var(--line);white-space:nowrap;font-size:11px}
table.raw td{padding:6px 9px;border-bottom:1px solid #1d2637;white-space:nowrap}
table.raw tfoot td{border-top:1px solid var(--line);border-bottom:none;font-weight:650;background:#121a28}
table.raw .num{text-align:right;font-family:var(--mono)}
table.raw tr.wtr td{background:rgba(63,179,127,.05)}
table.raw tr.hi td{background:rgba(74,159,212,.08);font-weight:600}
table.raw td.mn{font-weight:600}
.tag{font-size:9.5px;color:#5b6678;margin-left:6px;font-weight:400}
.st{font-size:10px;margin-left:2px}
.sig3{color:#3fb37f;font-weight:700}.sig2{color:#3fb37f}.sig1{color:#e8a33d}
.dim{color:#5b6678}
.gw{color:#3fb37f}.rw{color:#e5484d}
.note{font-size:11.5px;color:#8b98ab;line-height:1.65;margin:10px 0 0}
.note b{color:#b9c4d4}
.note a,.lim a{color:#6cb6e8}
.lim{margin:0;padding-left:18px;font-size:12px;color:#8b98ab;line-height:1.7}
.lim li{margin-bottom:8px}.lim b{color:#b9c4d4}
.dis{margin-top:14px;padding-top:12px;border-top:1px solid var(--line);color:#5b6678}
.ix{display:none}
</style></head><body>
'''

if __name__ == '__main__':
    main()
