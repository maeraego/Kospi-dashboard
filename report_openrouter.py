# -*- coding: utf-8 -*-
"""
report_openrouter.py  -  OpenRouter 회사별 토큰 차트 + 숫자를 텔레그램으로

collect_openrouter.py 가 쌓은 스냅샷으로 차트를 그린다.

  패널1  회사별 토큰 (상위 12) 막대 + 조단위 숫자 + 점유율
  패널2  진영별 점유율 (중국/미국/기타)
  패널3  스냅샷 추이 - 누적이 2회 이상일 때만. 1회면 안내문구.

사용법:
  python report_openrouter.py          # 차트 + 텔레그램 발송
  python report_openrouter.py --dry    # png 만 생성
"""
import os, sys, datetime
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
SRC = os.path.join(HERE, 'openrouter_monthly.parquet')
OUT_PNG = os.path.join(HERE, 'openrouter_report.png')
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
CN, US, ETC = '#e5484d', '#5b8def', '#8b5cf6'

# 진영 분류 (없는 회사는 기타)
CN_CO = {'deepseek', 'xiaomi', 'tencent', 'z-ai', 'minimax', 'moonshotai',
         'qwen', 'alibaba', 'stepfun', 'baidu', 'bytedance', '01-ai',
         'thudm', 'inclusionai', 'bytedance-research', 'zhipu'}
US_CO = {'anthropic', 'openai', 'google', 'nvidia', 'meta-llama', 'xai',
         'microsoft', 'amazon', 'cohere', 'perplexity', 'inflection',
         'liquid', 'ai21', 'sao10k'}

# ── 과거 추정치 (실측 아님) ────────────────────────────────────────────
# 출처: openrouter_monthly_chart_2.html (2026-07-25 작성).
# 뉴스·블로그 스냅샷을 모아 주간→월간 ×4.3 환산, 점유율 선형 보간,
# 마지막 달은 부분 데이터 기반 추정. 단위 = 조(T) 토큰/월.
# OpenRouter API 는 과거를 주지 않으므로 참고용으로만 겹쳐 그린다.
# 실측 스냅샷이 쌓이면 이 구간은 자연스럽게 뒤로 밀린다.
EST_MONTHS = ['2025-07', '2025-08', '2025-09', '2025-10', '2025-11', '2025-12',
              '2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06',
              '2026-07']
EST_CN = [3, 4, 6, 8, 12, 18, 26, 38, 45, 50, 56, 58, 84]
EST_TOTAL = [22, 24, 28, 34, 43, 56, 72, 95, 108, 116, 126, 126, 140]


def camp(c):
    if c in CN_CO:
        return '중국/아시아'
    if c in US_CO:
        return '미국'
    return '기타'


def _style(ax, title):
    ax.set_facecolor(BG)
    ax.set_title(title, color=FG, fontsize=11, pad=8, loc='left')
    ax.tick_params(colors='#9aa4b2', labelsize=8)
    ax.grid(True, color=GRID, lw=.6, alpha=.7)
    for s in ax.spines.values():
        s.set_color(GRID)


def build():
    if not os.path.exists(SRC):
        print('  ! openrouter_monthly.parquet 없음 - collect_openrouter.py 먼저')
        return None, None
    df = pd.read_parquet(SRC)
    snaps = sorted(df['snapshot'].unique())
    cur = df[df['snapshot'] == snaps[-1]].sort_values('tokens', ascending=False)
    total = cur['tokens'].sum()
    asof = pd.Timestamp(snaps[-1]).strftime('%Y-%m-%d')

    fig = plt.figure(figsize=(12, 8), facecolor=BG)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.25, 1])
    fig.suptitle('OpenRouter 회사별 토큰 사용량', color=FG, fontsize=15,
                 x=.02, ha='left', weight='bold')

    # 패널1 - 회사별 상위 12
    ax = fig.add_subplot(gs[0, :])
    _style(ax, f'회사별 토큰 (최근 1개월 누적, {asof} 기준)')
    top = cur.head(12).iloc[::-1]
    colors = [{'중국/아시아': CN, '미국': US, '기타': ETC}[camp(c)]
              for c in top['company']]
    ax.barh(top['company'], top['tokens'] / 1e12, color=colors, height=.68)
    for i, (_, r) in enumerate(top.iterrows()):
        ax.annotate(f'{r["tokens"]/1e12:,.1f}조  ({r["tokens"]/total*100:.1f}%)',
                    (r['tokens'] / 1e12, i), color=FG, fontsize=8.5,
                    va='center', xytext=(5, 0), textcoords='offset points')
    ax.set_xlim(0, top['tokens'].max() / 1e12 * 1.3)
    ax.set_xlabel('조 토큰', color='#9aa4b2', fontsize=8)

    # 패널2 - 진영별
    ax = fig.add_subplot(gs[1, 0])
    _style(ax, '진영별 점유율')
    cur = cur.copy()
    cur['진영'] = cur['company'].map(camp)
    grp = cur.groupby('진영')['tokens'].sum().sort_values(ascending=False)
    cmap = {'중국/아시아': CN, '미국': US, '기타': ETC}
    left = 0
    for name, v in grp.items():
        pct = v / total * 100
        ax.barh([0], [pct], left=left, color=cmap.get(name, ETC), height=.5)
        if pct > 7:
            ax.annotate(f'{name}\n{pct:.1f}%', (left + pct / 2, 0), color='#0f1115',
                        fontsize=9, weight='bold', ha='center', va='center')
        left += pct
    ax.set_xlim(0, 100)
    ax.set_ylim(-.6, .6)
    ax.set_yticks([])
    ax.set_xlabel('%', color='#9aa4b2', fontsize=8)

    # 패널3 - 월별 추이 (점선=과거 추정, 실선=실측)
    ax = fig.add_subplot(gs[1, 1])
    _style(ax, '월별 총 토큰 추이  (점선=추정, 실선=실측)')
    ex = pd.to_datetime([m + '-01' for m in EST_MONTHS])
    ax.plot(ex, EST_TOTAL, ls='--', lw=1.6, color='#6b7280',
            marker='o', ms=3, label='전체(추정)')
    ax.plot(ex, EST_CN, ls='--', lw=1.6, color=CN, alpha=.75,
            marker='o', ms=3, label='중국/아시아(추정)')

    m_tot = df.groupby('snapshot')['tokens'].sum() / 1e12
    t2 = df.copy()
    t2['진영'] = t2['company'].map(camp)
    m_cn = (t2[t2['진영'] == '중국/아시아'].groupby('snapshot')['tokens'].sum()
            / 1e12).reindex(m_tot.index).fillna(0)
    ax.plot(m_tot.index, m_tot.values, lw=2.4, color=FG, marker='o', ms=6,
            label='전체(실측)', zorder=5)
    ax.plot(m_cn.index, m_cn.values, lw=2.4, color=CN, marker='o', ms=6,
            label='중국/아시아(실측)', zorder=5)
    ax.annotate(f'{m_tot.iloc[-1]:,.0f}조', (m_tot.index[-1], m_tot.iloc[-1]),
                color=FG, fontsize=10, weight='bold', xytext=(-4, 8),
                textcoords='offset points', ha='right')
    ax.set_ylabel('조 토큰/월', color='#9aa4b2', fontsize=8)
    lg = ax.legend(loc='upper left', fontsize=7, facecolor=BG, edgecolor=GRID)
    for x in lg.get_texts():
        x.set_color(FG)

    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    fig.text(.02, .015, f'출처: OpenRouter rankings API   생성 {stamp}',
             color='#6b7280', fontsize=8)
    fig.tight_layout(rect=[0, .03, 1, .95])
    fig.savefig(OUT_PNG, dpi=130, facecolor=BG)
    plt.close(fig)
    print(f'  차트 저장 -> {os.path.basename(OUT_PNG)}')

    L = [f'OpenRouter 토큰 사용량  ({asof} 기준, 최근 1개월)', '']
    L.append(f'전체 {total/1e12:,.1f}조 토큰 · {len(cur)}개 회사')
    L.append('')
    for _, r in cur.head(8).iterrows():
        L.append(f'  {r["company"]:14s} {r["tokens"]/1e12:6.1f}조  '
                 f'{r["tokens"]/total*100:4.1f}%')
    L.append('')
    for name, v in grp.items():
        L.append(f'  {name} {v/total*100:.1f}%')
    if len(snaps) >= 2:
        prev = df[df['snapshot'] == snaps[-2]]
        pt = prev['tokens'].sum()
        L.append('')
        L.append(f'직전 스냅샷 대비 전체 {(total/pt-1)*100:+.1f}%')
    L.append('')
    L.append(f'[참고] 과거 추정 {EST_MONTHS[0]} {EST_TOTAL[0]}조 '
             f'-> {EST_MONTHS[-1]} {EST_TOTAL[-1]}조')
    L.append('  추정 구간은 뉴스 스냅샷 기반이라 실측과 이어붙이면 안 됩니다')
    return OUT_PNG, '\n'.join(L)


def send(png, caption):
    import requests
    token = os.environ.get('TELEGRAM_TOKEN')
    chat = os.environ.get('MY_TELEGRAM_ID')
    if not token or not chat:
        print('  ! TELEGRAM_TOKEN / MY_TELEGRAM_ID 없음 - 발송 건너뜀')
        return
    with open(png, 'rb') as f:
        r = requests.post(f'https://api.telegram.org/bot{token}/sendPhoto',
                          data={'chat_id': chat, 'caption': caption[:1024]},
                          files={'photo': f}, timeout=60)
    r.raise_for_status()
    print('  텔레그램 발송 완료')


if __name__ == '__main__':
    try:
        png, cap = build()
        if png:
            print('  ---- 캡션 ----')
            print('  ' + cap.replace('\n', '\n  '))
            if DRY:
                print('  (--dry: 발송 안 함)')
            else:
                send(png, cap)
    except Exception as e:
        print(f'  ! 리포트 실패: {type(e).__name__}: {e}')
    sys.exit(0)
