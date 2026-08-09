# -*- coding: utf-8 -*-
"""
report_dram.py  -  DRAM 가격 차트 4장 + 숫자를 텔레그램으로 발송

collect_dram.py 가 모은 데이터로 차트를 4개 파일로 따로 그리고,
텔레그램 앨범(sendMediaGroup)으로 한 번에 보낸다.
앨범이라 알림은 1회지만 이미지는 4장이 각각 확대해서 볼 수 있다.

  1 dram_1_price.png     DRAM 수출물가지수 (최근 10년)
  2 dram_2_yoy.png       전년동월비
  3 dram_3_value_vol.png 수출 금액지수 vs 물량지수
  4 dram_4_spot.png      TrendForce 현물가 / 계약가

각 차트에 숫자를 직접 찍고, 캡션에도 텍스트로 넣어 이미지를 안 열어도 읽힌다.

사용법:
  python report_dram.py          # 차트 4장 + 텔레그램 발송
  python report_dram.py --dry    # png 만 생성
"""
import os, sys, json, datetime
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHLY = os.path.join(HERE, 'dram_monthly.parquet')
SPOT = os.path.join(HERE, 'dram_spot_weekly.parquet')
CONTRACT = os.path.join(HERE, 'dram_contract.parquet')
DRY = '--dry' in sys.argv

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, '.env'))
except ImportError:
    pass

for cand in ('Malgun Gothic', 'NanumGothic', 'Batang', 'Gulim'):
    if any(f.name == cand for f in font_manager.fontManager.ttflist):
        plt.rcParams['font.family'] = cand
        break
plt.rcParams['axes.unicode_minus'] = False

BG, FG, GRID = '#0f1115', '#e6e6e6', '#2a2f3a'
UP, DOWN, ACC, BLUE = '#3fb37f', '#e5484d', '#d9a441', '#5b8def'


def _fig(title, sub):
    fig, ax = plt.subplots(figsize=(9, 5.2), facecolor=BG)
    ax.set_facecolor(BG)
    fig.suptitle(title, color=FG, fontsize=14, x=.02, ha='left', weight='bold')
    ax.set_title(sub, color='#9aa4b2', fontsize=9.5, pad=8, loc='left')
    ax.tick_params(colors='#9aa4b2', labelsize=8.5)
    ax.grid(True, color=GRID, lw=.6, alpha=.7)
    for s in ax.spines.values():
        s.set_color(GRID)
    return fig, ax


def _save(fig, name):
    p = os.path.join(HERE, name)
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    fig.text(.02, .02, f'출처: 한국은행 ECOS · TrendForce 공개자료   {stamp}',
             color='#6b7280', fontsize=7.5)
    fig.tight_layout(rect=[0, .04, 1, .94])
    fig.savefig(p, dpi=130, facecolor=BG)
    plt.close(fig)
    return p


def build():
    if not os.path.exists(MONTHLY):
        print('  ! dram_monthly.parquet 없음 - collect_dram.py 를 먼저 실행하세요')
        return []
    df = pd.read_parquet(MONTHLY)
    dram = df['DRAM수출물가'].dropna()
    last, prev = dram.iloc[-1], dram.iloc[-2]
    mo = dram.index[-1].strftime('%Y-%m')
    recent = dram[dram.index >= dram.index[-1] - pd.DateOffset(years=10)]
    lo = recent.min()
    yoy = (dram.pct_change(12) * 100).dropna()
    yoy_r = yoy[yoy.index >= yoy.index[-1] - pd.DateOffset(years=10)]
    out = []

    # 1 - 수출물가지수
    fig, ax = _fig('DRAM 수출물가지수',
                   f'2020=100 · 최근 10년 · {mo} 기준')
    ax.plot(recent.index, recent.values, color=UP, lw=2)
    ax.fill_between(recent.index, recent.values, lo, color=UP, alpha=.12)
    ax.scatter([dram.index[-1]], [last], color=UP, s=55, zorder=5)
    ax.annotate(f'{last:,.1f}', (dram.index[-1], last), color=UP, fontsize=16,
                weight='bold', xytext=(-14, 8), textcoords='offset points',
                ha='right')
    ax.annotate(f'10년 최저 {lo:,.1f}', (recent.idxmin(), lo), color='#9aa4b2',
                fontsize=8.5, xytext=(6, -16), textcoords='offset points')
    out.append((_save(fig, 'dram_1_price.png'),
                f'① DRAM 수출물가지수  {last:,.1f}  ({mo})\n'
                f'   전월비 {(last/prev-1)*100:+.1f}%\n'
                f'   10년 최저 {lo:,.1f} 대비 {last/lo:.1f}배'))

    # 2 - YoY
    fig, ax = _fig('DRAM 수출물가 전년동월비',
                   f'% · 최근 10년 · {mo} 기준')
    ax.bar(yoy_r.index, yoy_r.values, width=25,
           color=[UP if v >= 0 else DOWN for v in yoy_r.values])
    ax.axhline(0, color='#9aa4b2', lw=.8)
    ax.annotate(f'{yoy.iloc[-1]:+.1f}%', (yoy.index[-1], yoy.iloc[-1]),
                color=UP if yoy.iloc[-1] >= 0 else DOWN, fontsize=16,
                weight='bold', xytext=(-8, 6), textcoords='offset points',
                ha='right')
    pos = (yoy_r > 0).sum()
    out.append((_save(fig, 'dram_2_yoy.png'),
                f'② 전년동월비  {yoy.iloc[-1]:+.1f}%\n'
                f'   최근 10년 중 상승 {pos}개월 / 하락 {len(yoy_r)-pos}개월\n'
                f'   10년 최고 {yoy_r.max():+.1f}% · 최저 {yoy_r.min():+.1f}%'))

    # 3 - 금액 vs 물량
    fig, ax = _fig('반도체 수출 금액지수 vs 물량지수',
                   f'2020=100 · 최근 10년 · {mo} 기준')
    amt = df['반도체수출금액지수'].dropna()
    vol = df['반도체수출물량지수'].dropna()
    a_r = amt[amt.index >= amt.index[-1] - pd.DateOffset(years=10)]
    v_r = vol[vol.index >= vol.index[-1] - pd.DateOffset(years=10)]
    ax.plot(a_r.index, a_r.values, color=ACC, lw=2, label='금액')
    ax.plot(v_r.index, v_r.values, color=BLUE, lw=2, label='물량')
    ax.fill_between(a_r.index, a_r.values, v_r.reindex(a_r.index).values,
                    color=ACC, alpha=.10)
    ax.annotate(f'금액 {amt.iloc[-1]:,.0f}', (amt.index[-1], amt.iloc[-1]),
                color=ACC, fontsize=12, weight='bold', xytext=(-10, 6),
                textcoords='offset points', ha='right')
    ax.annotate(f'물량 {vol.iloc[-1]:,.0f}', (vol.index[-1], vol.iloc[-1]),
                color=BLUE, fontsize=12, weight='bold', xytext=(-10, -20),
                textcoords='offset points', ha='right',
                bbox=dict(boxstyle='round,pad=0.2', fc=BG, ec='none', alpha=.85))
    lg = ax.legend(loc='upper left', fontsize=9, facecolor=BG, edgecolor=GRID)
    for t in lg.get_texts():
        t.set_color(FG)
    out.append((_save(fig, 'dram_3_value_vol.png'),
                f'③ 반도체 수출  금액 {amt.iloc[-1]:,.1f} / 물량 {vol.iloc[-1]:,.1f}\n'
                f'   금액이 물량의 {amt.iloc[-1]/vol.iloc[-1]:.2f}배 = 단가 효과\n'
                f'   ※ 절대 달러금액이 아니라 지수(2020=100)'))

    # 4 - 현물/계약
    fig, ax = _fig('TrendForce 현물가 / 계약가', 'USD · 로그축 · 세션 평균')
    bars, labels, colors, cap = [], [], [], []
    for path, tag, c in ((SPOT, '현물', UP), (CONTRACT, '계약', ACC)):
        if not os.path.exists(path):
            continue
        row = pd.read_parquet(path).iloc[-1].dropna().sort_values(ascending=False)
        cap.append(f'[{tag}가]')
        for k, v in row.head(5).items():
            bars.append(float(v))
            labels.append(f'[{tag}] {k[:28]}')
            colors.append(c)
            cap.append(f'  {k[:30]}  ${v:,.2f}')
    if bars:
        y = list(range(len(bars)))
        ax.barh(y, bars, color=colors, height=.65)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8, color=FG)
        ax.invert_yaxis()
        # 칩 $4 ~ 서버모듈 $1,545 로 자릿수 차이가 커서 로그축을 쓴다
        ax.set_xscale('log')
        ax.set_xlim(1, max(bars) * 6)
        for i, v in enumerate(bars):
            ax.annotate(f'${v:,.2f}', (v, i), color=FG, fontsize=8.5,
                        va='center', xytext=(5, 0), textcoords='offset points')
    else:
        ax.text(.5, .5, '현물/계약 데이터 없음', color='#9aa4b2',
                ha='center', transform=ax.transAxes)
    out.append((_save(fig, 'dram_4_spot.png'),
                '④ TrendForce 현물가 / 계약가\n' + '\n'.join(cap)))

    # 5 - 현물 vs 계약 월별 겹침 (과거는 추정, 최신은 실측)
    out.append(_spot_contract_monthly())
    return out


# 오늘 측정한 실측값과 짝지을 대표 품목
#   현물 스크랩 이름 -> (계약 스크랩 이름, 과거추정 시리즈 이름)
PAIRS = {
    'DDR4 16Gb (2Gx8) 3200': ('DDR4 16Gb 2Gx8', 'DDR4 16Gb'),
    'DDR5 16Gb (2Gx8) 4800/5600': (None, 'DDR5 16Gb'),
}
PAIR_COLOR = {'DDR4 16Gb': '#f97316', 'DDR5 16Gb': '#60a5fa'}


def _spot_contract_monthly():
    """대표 DRAM 2종의 현물 vs 계약을 월별로 겹쳐 그린다.

    과거 구간은 dram_history 의 추정치(실선/점선 흐리게),
    오늘 값은 collect_dram 이 받은 실측(굵은 점).
    둘을 한 선으로 잇지 않는다 - 출처가 달라 이으면 없는 급등이 생긴다.
    """
    import dram_history as dh
    spot_h, con_h = dh.monthly()

    fig, ax = _fig('DRAM 현물가 vs 계약가 (월별)',
                   '실선=현물 · 점선=계약 · 흐린 구간은 추정, 굵은 점이 실측')
    for name in ('DDR4 16Gb', 'DDR5 16Gb'):
        c = PAIR_COLOR[name]
        ax.plot(spot_h.index, spot_h[name], color=c, lw=2, alpha=.85,
                label=f'{name} 현물(추정)')
        ax.plot(con_h.index, con_h[name], color=c, lw=1.8, ls='--', alpha=.55,
                drawstyle='steps-post', label=f'{name} 계약(추정)')
        ax.annotate(f'${spot_h[name].iloc[-1]:,.0f}',
                    (spot_h.index[-1], spot_h[name].iloc[-1]), color=c,
                    fontsize=9, weight='bold', xytext=(4, 2),
                    textcoords='offset points')

    # 실측 점 얹기
    meas = []
    srow = (pd.read_parquet(SPOT).iloc[-1].dropna()
            if os.path.exists(SPOT) else pd.Series(dtype=float))
    crow = (pd.read_parquet(CONTRACT).iloc[-1].dropna()
            if os.path.exists(CONTRACT) else pd.Series(dtype=float))
    asof = (pd.read_parquet(SPOT).index[-1] if os.path.exists(SPOT)
            else pd.Timestamp.today())
    for sname, (cname, hname) in PAIRS.items():
        c = PAIR_COLOR[hname]
        if sname in srow.index:
            v = float(srow[sname])
            ax.scatter([asof], [v], color=c, s=90, zorder=6,
                       edgecolors='#0f1115', linewidths=1.5)
            ax.annotate(f'${v:,.2f}', (asof, v), color=c, fontsize=10,
                        weight='bold', xytext=(6, 6), textcoords='offset points')
            meas.append(f'   {hname} 현물(실측) ${v:,.2f}')
        if cname and cname in crow.index:
            v = float(crow[cname])
            ax.scatter([asof], [v], color=c, s=70, zorder=6, marker='s',
                       edgecolors='#0f1115', linewidths=1.5)
            meas.append(f'   {hname} 계약(실측) ${v:,.2f}')

    ax.set_ylabel('USD / chip', color='#9aa4b2', fontsize=8)
    lg = ax.legend(loc='upper left', fontsize=7.5, facecolor=BG, edgecolor=GRID)
    for t in lg.get_texts():
        t.set_color(FG)

    d4s, d4c = spot_h['DDR4 16Gb'].iloc[-1], con_h['DDR4 16Gb'].iloc[-1]
    cap = ['⑤ 현물 vs 계약 (월별, 대표 DRAM 2종)',
           f'   DDR4 16Gb 추정  현물 ${d4s:,.1f} / 계약 ${d4c:,.1f} '
           f'(괴리 {d4s-d4c:+,.1f})',
           f'   DDR5 16Gb 추정  현물 ${spot_h["DDR5 16Gb"].iloc[-1]:,.1f} / '
           f'계약 ${con_h["DDR5 16Gb"].iloc[-1]:,.1f}']
    cap += meas
    cap.append('   ※ 과거는 뉴스·TF 스냅샷 보간 추정. 실측 점과 이으면 안 됩니다')
    return _save(fig, 'dram_5_spot_contract.png'), '\n'.join(cap)


def send(items):
    import requests
    token = os.environ.get('TELEGRAM_TOKEN')
    chat = os.environ.get('MY_TELEGRAM_ID')
    if not token or not chat:
        print('  ! TELEGRAM_TOKEN / MY_TELEGRAM_ID 없음 - 발송 건너뜀')
        return
    media, files, handles = [], {}, []
    try:
        for i, (png, cap) in enumerate(items):
            key = f'f{i}'
            media.append({'type': 'photo', 'media': f'attach://{key}',
                          'caption': cap[:1024]})
            fh = open(png, 'rb')
            handles.append(fh)
            files[key] = fh
        r = requests.post(f'https://api.telegram.org/bot{token}/sendMediaGroup',
                          data={'chat_id': chat,
                                'media': json.dumps(media, ensure_ascii=False)},
                          files=files, timeout=90)
        r.raise_for_status()
    finally:
        for fh in handles:
            fh.close()
    print(f'  텔레그램 앨범 발송 완료 ({len(items)}장)')


if __name__ == '__main__':
    try:
        items = build()
        for png, cap in items:
            print(f'  {os.path.basename(png)}')
            print('    ' + cap.replace('\n', '\n    '))
        if items:
            if DRY:
                print('  (--dry: 발송 안 함)')
            else:
                send(items)
    except Exception as e:
        print(f'  ! 리포트 실패: {type(e).__name__}: {e}')
    sys.exit(0)
