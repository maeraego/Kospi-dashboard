# -*- coding: utf-8 -*-
"""
check_setup.py  —  파일이 제자리에 있는지 점검하고, 다른 폴더에 흩어진 파일을 찾아준다.

사용법:  C:/python312/python.exe check_setup.py
        (자동으로 옮기려면)  C:/python312/python.exe check_setup.py --fix
"""
import os, sys, shutil

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
FIX  = '--fix' in sys.argv

SCRIPTS = ['collect_krx.py', 'collect_ecos.py', 'collect_fred.py',
           'collect_flow.py', 'update_all.py', 'update_fwd_per.py', 'build_dashboard.py',
           'serve_dashboard.py']
DATA    = ['krx_monthly.parquet', 'krx_daily.parquet',
           'ecos_monthly.parquet', 'ecos_daily.parquet',
           'fred_monthly.parquet', 'fred_daily.parquet',
           'flow_monthly.parquet', 'flow_daily.parquet',
           'fwd_per_monthly.parquet']

# 흩어져 있을 만한 후보 폴더
CANDIDATES = [r'C:\python312', os.path.expanduser('~'),
              os.path.join(os.path.expanduser('~'), 'Downloads'),
              os.path.join(os.path.expanduser('~'), 'Desktop'),
              os.getcwd()]

def show(title, items):
    print(f"\n{title}")
    for ok, name, note in items:
        mark = ' OK ' if ok else 'MISS'
        print(f"  [{mark}] {name}{'   ' + note if note else ''}")

print("=" * 58)
print(f"  작업 폴더: {HERE}")
print("=" * 58)

missing = []
rows = []
for f in SCRIPTS + DATA:
    ok = os.path.exists(os.path.join(HERE, f))
    note = ''
    if not ok:
        # 다른 폴더에서 찾아보기
        for c in CANDIDATES:
            if not c or os.path.abspath(c) == os.path.abspath(HERE):
                continue
            p = os.path.join(c, f)
            if os.path.exists(p):
                note = f'-> 발견: {p}'
                missing.append((f, p))
                break
        else:
            note = '-> 못 찾음'
    rows.append((ok, f, note))

show("파일 점검 (스크립트)", rows[:len(SCRIPTS)])
show("파일 점검 (데이터)",  rows[len(SCRIPTS):])

optional = {'ecos_daily.parquet', 'fred_daily.parquet', 'fwd_per_monthly.parquet',
            'flow_daily.parquet', 'flow_monthly.parquet'}
critical_missing = [f for ok, f, n in rows
                    if not ok and f not in optional and '발견' not in n]

if missing:
    print(f"\n다른 폴더에서 {len(missing)}개 파일을 찾았습니다.")
    if FIX:
        print("복사합니다...")
        for f, src in missing:
            try:
                shutil.copy2(src, os.path.join(HERE, f))
                print(f"  복사 완료: {f}")
            except Exception as e:
                print(f"  실패: {f}  ({e})")
        print("\n다시 점검하려면 이 스크립트를 한 번 더 실행하세요.")
    else:
        print("자동으로 옮기려면 아래를 실행하세요:")
        print(f"   {os.path.basename(sys.executable)} check_setup.py --fix")
elif critical_missing:
    print("\n[주의] 아래 파일을 찾지 못했습니다. 수집을 다시 돌려야 합니다:")
    for f in critical_missing:
        print(f"   - {f}")
    print("\n   python update_all.py")
else:
    print("\n모든 파일이 제자리에 있습니다. 아래를 실행하세요:")
    print("   python serve_dashboard.py      (또는 run_dashboard.bat 더블클릭)")

# .env 점검
env = os.path.join(HERE, '.env')
print("\n" + "-" * 58)
if os.path.exists(env):
    try:
        keys = [l.split('=')[0].strip() for l in open(env, encoding='utf-8')
                if '=' in l and not l.strip().startswith('#')]
        need = ['KRX_ID', 'KRX_PW', 'ECOS_KEY', 'FRED_KEY']
        print(".env 감지됨. 키 목록:", ', '.join(keys) if keys else '(비어 있음)')
        lack = [k for k in need if k not in keys]
        if lack:
            print("  [주의] 누락된 키:", ', '.join(lack))
    except Exception as e:
        print(f".env 읽기 실패: {e}")
else:
    print("[주의] .env 파일이 없습니다. KRX_ID/KRX_PW, ECOS_KEY, FRED_KEY 가 필요합니다.")
print("-" * 58)
