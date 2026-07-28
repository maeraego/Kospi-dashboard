# -*- coding: utf-8 -*-
"""M1/M2 신호의 IC와 가중치를 확인한다."""
import io, contextlib, importlib.util, sys, os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

spec = importlib.util.spec_from_file_location('bd', 'build_dashboard.py')
m = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()):
    spec.loader.exec_module(m)

for ix in ['KOSPI', 'KOSDAQ']:
    a = m.analyze(ix)
    print(f"\n===== {ix} =====")
    print(f"{'신호':16s} {'IC':>7s} {'가중':>7s} {'상태':>10s}")
    for n in sorted(a['w'], key=lambda x: -a['w'][x]):
        ic = a['ic'][n]; w = a['w'][n]
        is_m = ('M2' in n) or ('M1' in n) or ('시가총액/M2' in n)
        if not is_m:
            continue
        status = '가중O' if w > 0 else ('IC<0.10' if ic < 0.10 else '표본부족')
        print(f"  {n:14s} {ic:7.3f} {w*100:6.1f}% {status:>10s}")
    # 현재값도
    print("  현재값:")
    for r in a['reads']:
        if 'M2' in r[0] or 'M1' in r[0] or '시가총액/M2' in r[0]:
            print(f"    {r[0]:16s} {r[3]:>10.3f}   백분위 {r[4]:.0f}%")
