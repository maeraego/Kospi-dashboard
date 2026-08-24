# -*- coding: utf-8 -*-
"""
check_median_logic.py — 예측 중앙값이 어떤 산수로 나오는지 분해

질문: "점수 +0.21에서 어떻게 중앙값 7,519가 나오나? 상관계수만 있고
       회귀계수가 없으면 강도(얼마나 오를지)는 못 내지 않나?"

analyze() 안의 _proj_for()를 그대로 재현해 각 항의 기여를 숫자로 보여준다.
"""
import io
import contextlib
import importlib.util
import sys
import os
import numpy as np
import pandas as pd

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
bd = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(bd)

df = bd.df   # NB는 analyze() 지역변수라 반환된 tbl에서 꺼낸다


def smooth_bins(xs, ys, nb):
    """build_dashboard._smooth_bins 와 동일."""
    o = np.argsort(xs)
    ys2 = np.asarray(ys)[o]
    n = len(ys2)
    win = max(int(n * 0.20), 8)
    out = []
    for b in range(nb):
        c = int((b + 0.5) / nb * n)
        lo, hi = max(0, c - win // 2), min(n, c + win // 2)
        out.append(float(np.mean(ys2[lo:hi])))
    return out


def explain(idx='KOSPI'):
    a = bd.analyze(idx)
    NB = a['tbl']['NB']
    sc, cur, cbin = a['sc'], a['cur'], a['cbin']
    px = a['px']

    # ── 1) 장기 CAGR 앵커 ──
    P = df[f'{idx}_종가'].dropna()
    base_val, base_dt = (100.0, pd.Timestamp('1980-01-04')) if idx == 'KOSPI' \
        else (1000.0, pd.Timestamp('1996-07-01'))
    yrs = max((P.index[-1] - base_dt).days / 365.25, 1)
    cagr_log = float(np.log(P.iloc[-1] / base_val) / yrs)

    # ── 2) 국면 프리미엄 ──
    xy = pd.concat([sc.rename('s'), bd.fwd(idx, 12).rename('y')],
                   axis=1, sort=True).dropna()
    raw_means = smooth_bins(xy['s'].values, xy['y'].values, NB)
    bar12 = sum(raw_means) / NB

    xys = xy.sort_values('s').reset_index(drop=True)
    win = max(int(len(xys) * 0.20), 8)
    c = int((cbin + 0.5) / NB * len(xys))
    seg = xys['y'].iloc[max(0, c - win // 2):min(len(xys), c + win // 2)]

    prem_raw = float(seg.mean()) - bar12
    prem = prem_raw * 0.5
    center = cagr_log + prem
    med = px * np.exp(center)

    print("=" * 72)
    print(f"  {idx} 예측 중앙값 분해   (현재가 {px:,.1f}, 점수 {cur:+.2f}, 구간 {cbin+1}/{NB})")
    print("=" * 72)
    print(f"""
  [1] 장기추세 앵커 (CAGR)
      {idx} 기준점 {base_val:,.0f} ({base_dt.date()}) → 현재 {px:,.1f}
      경과 {yrs:.1f}년 → 연 로그수익 {cagr_log:.4f} = 연 {np.exp(cagr_log)-1:+.2%}
      이것만으로 12개월 뒤  →  {px*np.exp(cagr_log):,.0f}

  [2] 국면 프리미엄
      현재 구간({cbin+1}/{NB}) 과거 12개월 평균수익 : {seg.mean():+.4f} (로그, n={len(seg)})
      {NB}개 구간 평균들의 평균               : {bar12:+.4f}
      차이(이 국면이 평균보다 얼마나 좋은가)   : {prem_raw:+.4f}
      축소계수 0.5 적용                      : {prem:+.4f}

  [3] 합산
      center = CAGR({cagr_log:+.4f}) + 프리미엄({prem:+.4f}) = {center:+.4f}
      중앙값 = {px:,.1f} x exp({center:.4f}) = {med:,.0f}
""")
    print(f"  기여도 분해 (총 {np.exp(center)-1:+.2%} 중)")
    print(f"      장기추세 CAGR   {np.exp(cagr_log)-1:+7.2%}   <- 대부분")
    print(f"      국면 프리미엄   {prem:+7.2%}   <- 점수가 하는 일은 이것뿐")

    # ── 구간을 바꾸면 중앙값이 얼마나 달라지나 ──
    print(f"\n  [검증] 점수가 다른 구간이었다면 중앙값은?")
    print(f"      {'구간':<6s} {'구간평균':>9s} {'프리미엄x0.5':>12s} {'중앙값':>10s}")
    for b in range(NB):
        cc = int((b + 0.5) / NB * len(xys))
        sg = xys['y'].iloc[max(0, cc - win // 2):min(len(xys), cc + win // 2)]
        pr = (float(sg.mean()) - bar12) * 0.5
        mk = '  <- 지금' if b == cbin else ''
        print(f"      {b+1}/{NB}    {sg.mean():>+9.4f} {pr:>+12.4f} "
              f"{px*np.exp(cagr_log+pr):>10,.0f}{mk}")

    # ── 점수 크기가 구간 안에서 의미가 있나 ──
    print(f"\n  [검증] 같은 구간 안에서 점수 크기가 결과를 바꾸나?")
    # [주의] a['qedges']를 쓰면 안 된다. analyze() 816행이 edges를 켈리 베팅용
    #   4분위로 덮어쓴 뒤 871행이 그걸 내보내서, 국면 경계가 아니라 켈리 경계가 담긴다.
    #   (JS는 이미 이 값을 안 읽고 백분위 방식을 쓴다.) 여기서도 _bins와 같은 방식을 쓴다.
    b = np.clip((xy['s'].rank(pct=True) * NB).astype(int), 0, NB - 1)
    inb = xy[b == cbin]
    if len(inb) > 10:
        lo_h = inb[inb['s'] <= inb['s'].median()]['y'].mean()
        hi_h = inb[inb['s'] > inb['s'].median()]['y'].mean()
        r = inb['s'].corr(inb['y'])
        print(f"      구간 {cbin+1} 표본 {len(inb)}개")
        print(f"      점수 하위 절반 평균수익 {lo_h:+.4f} / 상위 절반 {hi_h:+.4f}")
        print(f"      구간 내 점수-수익 상관 = {r:+.3f}"
              f"  ({'거의 무관' if abs(r) < 0.2 else '유의미'})")


if __name__ == '__main__':
    explain('KOSPI')
