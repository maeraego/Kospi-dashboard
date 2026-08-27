# -*- coding: utf-8 -*-
"""
backfill_proj_history.py  -  예측 이력을 과거 구간까지 재구성해 채운다

proj_history.json 은 빌드할 때마다 한 줄씩 쌓이므로, 도입 직후에는
비교할 직전 기록이 없어 변화 표가 나오지 않는다. 과거 월말 시점의
가격과 종합점수로 예측 중앙값을 되짚어 미리 채워 넣는다.

[중요] 재구성 값은 실제 기록이 아니다.
  국면별 프리미엄은 '현재 시점 모델'에서 뽑아 과거 가격·점수에 적용한다.
  당시 모델이 실제로 내놨을 값과는 다를 수 있다(그때는 데이터가 더 적었다).
  그래서 src='recon' 으로 표시하고, 화면에서도 구분해 보여준다.
  실제 빌드가 남긴 기록은 src='live'.

  · 가격/점수는 그 시점의 실제 값 (여기는 재구성이 아니다)
  · 백분위는 그 시점까지의 과거만으로 계산 (룩어헤드 방지)
  · 프리미엄/밴드 비율만 현재 모델 것을 빌려온다

사용법:  C:/python312/python.exe backfill_proj_history.py [개월수]
         (기본 24개월. 이미 있는 날짜는 건드리지 않는다)
"""
import io, sys, json, contextlib, os
import numpy as np, pandas as pd

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with contextlib.redirect_stdout(io.StringIO()):
    import build_dashboard as bd

MONTHS = int(sys.argv[1]) if len(sys.argv) > 1 else 24
PATH = bd.PROJ_HIST


def recon(ix, months):
    a = bd.analyze(ix)
    pb, NB = a['tbl']['projbins'], a['tbl']['NB']
    px_now = float(a['tbl']['px_now'])
    asof = a['asof']
    yrs_now = (asof.year - 1980) + (asof.month - 1) / 12.0
    cagr_now = np.log(px_now / 100.0) / yrs_now

    # 국면별 프리미엄과 밴드 비율을 현재 모델에서 뽑는다
    prem, ratio = {}, {}
    for b, v in pb.items():
        m = float(v['med'])
        prem[b] = float(np.log(m / px_now) - cagr_now)
        ratio[b] = {k: [float(x) / m for x in v['bands'][k]] for k in (50, 90)}

    sc = a['sc'].dropna()
    px = bd.df[f'{ix}_종가'].dropna()
    # 진행 중인 당월은 제외한다. 월말 날짜(예: 2026-08-31)로 기록되어
    # 오늘보다 미래가 되고, 같은 달을 실기록과 중복해서 담게 된다.
    cur_ym = (asof.year, asof.month)
    out = []
    for t in sc.index[-months:]:
        if t not in px.index or (t.year, t.month) == cur_ym:
            continue
        p = float(px.loc[t])
        past = sc.loc[:t]
        if len(past) < 60:
            continue
        pct = float((past.iloc[:-1] < past.iloc[-1]).mean())   # 룩어헤드 방지
        b = min(int(pct * NB), NB - 1)
        if b not in prem:
            continue
        yrs = (t.year - 1980) + (t.month - 1) / 12.0
        base = float(np.log(p / 100.0) / yrs)
        med = p * float(np.exp(base + prem[b]))
        out.append({
            'date': t.strftime('%Y-%m-%d'), 'asof': t.strftime('%Y-%m'),
            'idx': ix, 'src': 'recon',
            'px': round(p, 2), 'med': round(med, 2),
            'score': round(float(sc.loc[t]), 3), 'pct': round(pct, 4),
            'regime': bd.regime(pct)[0],
            'base_log': round(base, 5), 'prem_log': round(prem[b], 5),
            'b50': [round(med * ratio[b][50][0], 2), round(med * ratio[b][50][1], 2)],
            'b90': [round(med * ratio[b][90][0], 2), round(med * ratio[b][90][1], 2)],
        })
    return out


try:
    hist = json.load(io.open(PATH, encoding='utf-8'))
except Exception:
    hist = []
have = {(h.get('date'), h.get('idx')) for h in hist}

added = 0
for ix in ('KOSPI', 'KOSDAQ'):
    rows = recon(ix, MONTHS)
    new = [r for r in rows if (r['date'], r['idx']) not in have]
    hist += new
    added += len(new)
    print(f'  {ix:7s} 재구성 {len(rows)}개월 중 신규 {len(new)}건')
    for r in new[-3:]:
        print(f'      {r["date"]}  현재가 {r["px"]:>9,.0f}  예측 {r["med"]:>9,.0f}  {r["regime"]}')

for h in hist:
    h.setdefault('src', 'live')          # 기존 기록은 실제 빌드 산물
hist.sort(key=lambda h: (h.get('date', ''), h.get('idx', '')))
io.open(PATH, 'w', encoding='utf-8').write(
    json.dumps(hist, ensure_ascii=False, indent=1))
print(f'\n총 {len(hist)}건 저장 (신규 {added}건) -> {os.path.basename(PATH)}')
