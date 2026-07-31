# -*- coding: utf-8 -*-
"""경기선행지수 순환참조 검증: IC 0.565가 진짜 경기 정보인가, 코스피 재탕인가.

민용님 지적: 경기선행지수에 코스피가 구성항목으로 들어가 '선행'이 아니라 '동행'.
검증: 코스피 자체 성분을 제거한 뒤에도 IC가 남는가?
"""
import io, contextlib, importlib.util, sys, os
import numpy as np, pandas as pd
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m)
df = m.df

def ez(s, mp=36): return (s - s.expanding(mp).mean()) / s.expanding(mp).std()
def fwd(h=12):
    P = df['KOSPI_종가']; return np.log(P.shift(-h) / P)
y = fwd(12)
li = df['선행지수']
kospi_mom = df['KOSPI_종가'].pct_change(12)   # 코스피 12개월 모멘텀

def ic(x):
    xy = pd.concat([x.rename('x'), y.rename('y')], axis=1, sort=True).dropna()
    return xy['x'].corr(xy['y']), len(xy)

print("=" * 64)
print("  경기선행지수 순환참조 검증")
print("=" * 64)

c0, n0 = ic(ez(li) * -1)
print(f"\n  [원본] 경기선행지수 IC = {c0:+.3f} (n={n0})")

# 코스피 모멘텀 제거 (순위 기반, 극단에 강건)
c = pd.concat([li.rename('li'), kospi_mom.rename('k')], axis=1, sort=True).dropna()
rli, rk = c['li'].rank(pct=True), c['k'].rank(pct=True)
resid = rli - np.polyfit(rk, rli, 1)[0] * rk
c1, n1 = ic(ez(resid) * -1)
print(f"  [코스피 성분 제거후] IC = {c1:+.3f}")
print(f"  → 유지율: {abs(c1/c0)*100:.0f}%  ({'대부분 진짜 경기정보' if abs(c1)>abs(c0)*0.6 else '상당부분 코스피 재탕'})")

# 시차 검증: 선행지수 YoY와 코스피 YoY의 최대상관 시점
print("\n  ── 선행/동행 판별: 어느 시차에서 상관 최대? ──")
liy = li.pct_change(12)
best = None
for lag in range(-6, 7):
    xy = pd.concat([liy.rename('li'), kospi_mom.shift(lag).rename('k')], axis=1, sort=True).dropna()
    r = xy['li'].corr(xy['k'])
    if best is None or abs(r) > abs(best[1]): best = (lag, r)
    mark = ' ←최대' if best and lag == best[0] else ''
    if lag in (-3, -1, 0, 1, 3):
        print(f"    코스피 {lag:+d}개월: 상관 {r:+.2f}{mark}")
print(f"\n  최대상관 시차: {best[0]:+d}개월")
if best[0] > 0:
    print("  → 코스피가 선행지수보다 앞선다 = 선행지수는 '동행/후행' (순환참조 확정)")
elif best[0] < 0:
    print("  → 선행지수가 코스피보다 앞선다 = 진짜 선행지표")
else:
    print("  → 동시 = 동행지표")

# 결론: 만약 순환참조면, 코스피 성분 제거한 IC를 써야 공정
print("\n" + "=" * 64)
print("  판정")
print("=" * 64)
print(f"  원본 IC {c0:+.3f} 중 코스피 재탕 부분: {abs(c0)-abs(c1):+.3f}")
print(f"  순수 경기정보 IC: {c1:+.3f}")
print("  → 가중치를 순수 경기정보 IC 기준으로 낮추면 다른 신호가 제 몫을 받음")
