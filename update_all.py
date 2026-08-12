# -*- coding: utf-8 -*-
"""
update_all.py  -  원클릭 데이터 갱신
  KRX(코스피/코스닥) + ECOS(국내매크로) + FRED(글로벌매크로)를 순서대로 수집.
사용법:  C:/python312/python.exe update_all.py
필요:    .env 에  KRX_ID/KRX_PW, ECOS_KEY, FRED_KEY  (같은 폴더)
결과:    krx_*.parquet, ecos_*.parquet, fred_*.parquet 최신화
"""
import subprocess, sys, time, os

# 윈도우 cp949 콘솔에서도 깨지지 않도록
os.environ.setdefault('PYTHONIOENCODING','utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PY = sys.executable  # 지금 실행 중인 파이썬 그대로 사용
HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("KRX  (코스피/코스닥)", "collect_krx.py"),
    ("ECOS (국내 매크로)",   "collect_ecos.py"),
    ("FRED (글로벌 매크로)", "collect_fred.py"),
    ("KOFIA(신용잔고·예탁금)", "collect_kofia.py"),
    ("VKOSPI(변동성지수)",   "collect_vkospi.py"),
    ("FLOW (투자자별 수급)", "collect_flow.py"),
]

def run(label, script):
    path = os.path.join(HERE, script)
    if not os.path.exists(path):
        print(f"  ! {script} 없음 - 건너뜀")
        return False
    print(f"\n{'='*56}\n> {label}   [{script}]\n{'='*56}")
    t0 = time.time()
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    r = subprocess.run([PY, path], cwd=HERE, env=env)
    ok = (r.returncode == 0)
    print(f"  {'[OK] 완료' if ok else '[FAIL] 실패(코드 %d)'%r.returncode}  ({time.time()-t0:.0f}s)")
    return ok

if __name__ == "__main__":
    print("데이터 전체 갱신 시작")
    results = {label: run(label, script) for label, script in STEPS}
    print(f"\n{'='*56}\n요약")
    for label, ok in results.items():
        print(f"  {'[OK]' if ok else '[FAIL]'}  {label}")
    if all(results.values()):
        print("\n전부 성공 → 이제 build_dashboard.py 로 대시보드를 갱신하세요.")
    else:
        print("\n일부 실패. 위 로그에서 해당 단계 확인 필요.")
