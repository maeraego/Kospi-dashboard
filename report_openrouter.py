# -*- coding: utf-8 -*-
"""
report_openrouter.py  -  OpenRouter 회사별 토큰 차트 3장 + 숫자를 텔레그램으로

collect_openrouter.py 가 쌓은 스냅샷으로 차트를 3개 파일로 따로 그리고,
텔레그램 앨범(sendMediaGroup)으로 한 번에 보낸다.

  1 or_1_company.png   회사별 토큰 (상위 12) + 조단위 숫자 + 점유율
  2 or_2_camp.png      진영별 점유율 (중국/아시아 · 미국 · 기타)
  3 or_3_trend.png     월별 총 토큰 추이 (점선=과거 추정, 실선=실측)

사용법:
  python report_openrouter.py          # 차트 3장 + 텔레그램 발송
  python report_openrouter.py --dry    # png 만 생성
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
SRC = os.path.join(HERE, 'openrouter_monthly.parquet')
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
CMAP = {'중국/아시아': CN, '미국': US, '기타': ETC}

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
    fig.text(.02, .02, f'출처: OpenRouter rankings API   {stamp}',
             color='#6b7280', fontsize=7.5)
    fig.tight_layout(rect=[0, .04, 1, .94])
    fig.savefig(p, dpi=130, facecolor=BG)
    plt.close(fig)
    return p


def build():
    if not os.path.exists(SRC):
        print('  ! openrouter_monthly.parquet 없음 - collect_openrouter.py 먼저')
        return []
    df = pd.read_parquet(SRC)
    snaps = sorted(df['snapshot'].unique())
    asof = pd.Timestamp(snaps[-1]).strftime('%Y-%m-%d')
    cur = df[df['snapshot'] == snaps[-1]].sort_values('tokens', ascending=False).copy()
    total = cur['tokens'].sum()
    cur['진영'] = cur['company'].map(camp)
    grp = cur.groupby('진영')['tokens'].sum().sort_values(ascending=False)
    out = []

    # 1 - 회사별
    fig, ax = _fig('OpenRouter 회사별 토큰',
                   f'최근 1개월 누적 · {asof} 기준 · 전체 {total/1e12:,.1f}조')
    top = cur.head(12).iloc[::-1]
    ax.barh(top['company'], top['tokens'] / 1e12, height=.68,
            color=[CMAP[camp(c)] for c in top['company']])
    for i, (_, r) in enumerate(top.iterrows()):
        ax.annotate(f'{r["tokens"]/1e12:,.1f}조  ({r["tokens"]/total*100:.1f}%)',
                    (r['tokens'] / 1e12, i), color=FG, fontsize=8.5,
                    va='center', xytext=(5, 0), textcoords='offset points')
    ax.set_xlim(0, top['tokens'].max() / 1e12 * 1.32)
    ax.set_xlabel('조 토큰', color='#9aa4b2', fontsize=8)
    cap = [f'① 회사별 토큰 ({asof} 기준, 최근 1개월)',
           f'   전체 {total/1e12:,.1f}조 · {len(cur)}개 회사']
    for _, r in cur.head(8).iterrows():
        cap.append(f'   {r["company"]:13s} {r["tokens"]/1e12:6.1f}조 '
                   f'{r["tokens"]/total*100:5.1f}%')
    out.append((_save(fig, 'or_1_company.png'), '\n'.join(cap)))

    # 2 - 진영별
    fig, ax = _fig('진영별 점유율', f'{asof} 기준 · 토큰 기준')
    left = 0
    for name, v in grp.items():
        pct = v / total * 100
        ax.barh([0], [pct], left=left, color=CMAP.get(name, ETC), height=.45)
        if pct > 6:
            ax.annotate(f'{name}\n{pct:.1f}%', (left + pct / 2, 0),
                        color='#0f1115', fontsize=11, weight='bold',
                        ha='center', va='center')
        left += pct
    ax.set_xlim(0, 100)
    ax.set_ylim(-.5, .5)
    ax.set_yticks([])
    ax.set_xlabel('%', color='#9aa4b2', fontsize=8)
    cap = ['② 진영별 점유율']
    for name, v in grp.items():
        n = (cur['진영'] == name).sum()
        cap.append(f'   {name} {v/total*100:.1f}%  ({v/1e12:,.1f}조 · {n}개사)')
    out.append((_save(fig, 'or_2_camp.png'), '\n'.join(cap)))

    # 3 - 월별 추이
    fig, ax = _fig('월별 총 토큰 추이', '점선 = 과거 추정 · 실선 = 실측')
    ex = pd.to_datetime([m + '-01' for m in EST_MONTHS])
    ax.plot(ex, EST_TOTAL, ls='--', lw=1.6, color='#6b7280', marker='o', ms=3,
            label='전체(추정)')
    ax.plot(ex, EST_CN, ls='--', lw=1.6, color=CN, alpha=.75, marker='o', ms=3,
            label='중국/아시아(추정)')
    m_tot = df.groupby('snapshot')['tokens'].sum() / 1e12
    t2 = df.copy()
    t2['진영'] = t2['company'].map(camp)
    m_cn = (t2[t2['진영'] == '중국/아시아'].groupby('snapshot')['tokens'].sum()
            / 1e12).reindex(m_tot.index).fillna(0)
    ax.plot(m_tot.index, m_tot.values, lw=2.4, color=FG, marker='o', ms=7,
            label='전체(실측)', zorder=5)
    ax.plot(m_cn.index, m_cn.values, lw=2.4, color=CN, marker='o', ms=7,
            label='중국/아시아(실측)', zorder=5)
    ax.annotate(f'{m_tot.iloc[-1]:,.0f}조', (m_tot.index[-1], m_tot.iloc[-1]),
                color=FG, fontsize=13, weight='bold', xytext=(-6, 10),
                textcoords='offset points', ha='right')

    # 월별 상승률(MoM) 을 각 점 위에 작게
    for i in range(1, len(EST_TOTAL)):
        mom = (EST_TOTAL[i] / EST_TOTAL[i - 1] - 1) * 100
        ax.annotate(f'{mom:+.0f}%', (ex[i], EST_TOTAL[i]), color='#8b93a1',
                    fontsize=6.5, ha='center', xytext=(0, 7),
                    textcoords='offset points')

    # CAGR - 추정 시작점부터 실측 최신까지
    n_mon = ((m_tot.index[-1].year - ex[0].year) * 12
             + m_tot.index[-1].month - ex[0].month)
    growth = m_tot.iloc[-1] / EST_TOTAL[0]
    cagr = (growth ** (12 / n_mon) - 1) * 100 if n_mon else float('nan')
    avg_mom = (growth ** (1 / n_mon) - 1) * 100 if n_mon else float('nan')
    box = (f'{n_mon}개월  {EST_TOTAL[0]}조 → {m_tot.iloc[-1]:,.0f}조  ({growth:.1f}배)\n'
           f'연율 CAGR  {cagr:+,.0f}%\n'
           f'평균 월상승률  {avg_mom:+.1f}%')
    ax.text(.02, .97, box, transform=ax.transAxes, color=FG, fontsize=8.5,
            va='top', ha='left', linespacing=1.5,
            bbox=dict(boxstyle='round,pad=0.5', fc='#161a22', ec=GRID))

    ax.set_ylabel('조 토큰/월', color='#9aa4b2', fontsize=8)
    lg = ax.legend(loc='lower right', fontsize=7.5, facecolor=BG, edgecolor=GRID)
    for t in lg.get_texts():
        t.set_color(FG)
    cap = ['③ 월별 총 토큰 추이',
           f'   실측 {asof}  {m_tot.iloc[-1]:,.0f}조 '
           f'(중국/아시아 {m_cn.iloc[-1]:,.0f}조)',
           f'   추정 {EST_MONTHS[0]} {EST_TOTAL[0]}조 -> '
           f'{EST_MONTHS[-1]} {EST_TOTAL[-1]}조',
           f'   {n_mon}개월 {growth:.1f}배 · 연율 CAGR {cagr:+,.0f}% '
           f'· 평균 월상승 {avg_mom:+.1f}%',
           '   ※ 추정은 뉴스 스냅샷 기반. 실측과 이어붙이면 안 됩니다']
    if len(snaps) >= 2:
        pt = df[df['snapshot'] == snaps[-2]]['tokens'].sum()
        cap.append(f'   직전 스냅샷 대비 {(total/pt-1)*100:+.1f}%')
    out.append((_save(fig, 'or_3_trend.png'), '\n'.join(cap)))
    return out


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
