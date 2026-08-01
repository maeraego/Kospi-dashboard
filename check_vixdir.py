# -*- coding: utf-8 -*-
"""한국VIX 신호의 방향(부호)과 가중 상향 시 효과 검증.
   변동성 높을수록 이후수익 좋으므로(IC+0.19), 한국VIX는 '강세신호'여야 맞다.
   현재 이게 제대로 걸렸는지, 가중 올리면 지금 장을 '유리'로 잡는지 확인."""
import io, contextlib, importlib.util, sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except: pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(m)

a = m.analyze('KOSPI')
print("=== 한국VIX·VIX급등 방향 확인 ===")
for r in a['reads']:
    if r[0] in ['한국VIX', 'VIX 급등(YoY)', '일드갭 (예상PER)']:
        n, z, w = r[0], r[5], r[6]
        d = a['direction'].get(n, (None, None))
        # direction[n] = (eff, 역발상여부). eff>0이면 값 클수록 강세
        eff = d[0]
        way = '값 높을수록 강세(유리)' if eff and eff > 0 else '값 높을수록 약세(불리)'
        contrib = z * w if z else 0
        print(f"  {n:16s} z={z:+.2f} 가중{w*100:.1f}% 방향[{way}] → 점수기여 {contrib:+.3f}")
print()
print(f"현재 종합점수: {a['cur']:+.3f} (양수=유리)")
print()

# 한국VIX 가중을 올리면 점수가 어떻게 되나 (강세신호 가정)
ic = a['ic']
w0 = {r[0]: r[6] for r in a['reads'] if r[6] > 0}
cur_z = {r[0]: r[5] for r in a['reads'] if r[5] is not None}
tot = sum(w0.values())
w0 = {c: v/tot for c, v in w0.items()}

print("=== 한국VIX 가중 상향 시 종합점수 ===")
for floor in [0.03, 0.05, 0.08, 0.12]:
    wd = dict(w0)
    for v in ['한국VIX', 'VIX 급등(YoY)']:
        if v in wd: wd[v] = max(wd[v], floor)
    t = sum(wd.values()); wd = {c: vv/t for c, vv in wd.items()}
    ns = sum(cur_z.get(c, 0) * wd[c] for c in wd if c in cur_z)
    reg = '유리' if ns >= 0.1 else ('불리' if ns <= -0.1 else '중립')
    print(f"  변동성 하한 {floor*100:.0f}%: 점수 {ns:+.3f} [{reg}]  (한국VIX 가중 {wd.get('한국VIX',0)*100:.0f}%)")
