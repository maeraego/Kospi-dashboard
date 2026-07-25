# -*- coding: utf-8 -*-
"""
apply_update.py  —  다운로드 폴더에 받은 파일을 minyong-agent 폴더로 자동 적용

브라우저는 파일을 항상 '다운로드' 폴더에 저장한다(웹페이지가 위치를 못 정함).
이 스크립트가 그걸 찾아서 작업 폴더로 옮겨준다.

  · 이름이 겹쳐 생긴 "build_dashboard (1).py" 같은 파일도 인식
  · 여러 개면 가장 최근 것 선택
  · 기존 파일은 backup 폴더에 자동 백업 후 덮어씀
  · 다운로드본이 더 오래됐으면 건너뜀

사용법:  C:/python312/python.exe apply_update.py
        (확인 없이 바로 적용)  ... apply_update.py --yes
        (옮긴 뒤 대시보드까지 재생성)  ... apply_update.py --yes --build
"""
import os
import re
import sys
import shutil
import subprocess
from datetime import datetime

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
AUTO = '--yes' in sys.argv or '-y' in sys.argv
BUILD = '--build' in sys.argv

# 이 프로젝트에서 관리하는 파일들
TARGETS = [
    'build_dashboard.py', 'serve_dashboard.py', 'update_all.py',
    'update_fwd_per.py', 'check_setup.py', 'apply_update.py',
    'collect_krx.py', 'collect_ecos.py', 'collect_fred.py',
    'collect_flow.py', 'collect_fwd_per.py',
    'daily_update.bat', 'run_dashboard.bat', 'setup_schedule.bat',
    'requirements.txt',
]

HOME = os.path.expanduser('~')
SEARCH_DIRS = [
    os.path.join(HOME, 'Downloads'),
    os.path.join(HOME, 'Desktop'),
    os.path.join(HOME, '다운로드'),
    os.path.join(HOME, '바탕 화면'),
]


def newest_match(folder, target):
    """폴더에서 target(또는 'target (1)' 형태) 중 가장 최근 파일을 찾는다."""
    if not os.path.isdir(folder):
        return None
    stem, ext = os.path.splitext(target)
    pat = re.compile(r'^' + re.escape(stem) + r'(?:\s*\(\d+\))?' + re.escape(ext) + r'$',
                     re.IGNORECASE)
    found = []
    try:
        for name in os.listdir(folder):
            if pat.match(name):
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    found.append((os.path.getmtime(p), p))
    except Exception:
        return None
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


print("=" * 60)
print(f"  작업 폴더: {HERE}")
print("=" * 60)

plan = []
for t in TARGETS:
    best = None
    for d in SEARCH_DIRS:
        p = newest_match(d, t)
        if p and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
            best = p
    if not best:
        continue
    dst = os.path.join(HERE, t)
    src_m = os.path.getmtime(best)
    if os.path.exists(dst):
        dst_m = os.path.getmtime(dst)
        if src_m <= dst_m:
            continue                      # 다운로드본이 더 오래됨 → 건너뜀
        state = '갱신'
    else:
        state = '신규'
    plan.append((t, best, state, src_m))

if not plan:
    print("\n적용할 새 파일이 없습니다.")
    print("  (다운로드 폴더에 더 최신인 파일이 없거나, 이미 모두 적용됨)")
    sys.exit(0)

print(f"\n적용 대상 {len(plan)}개:\n")
for t, src, state, m in plan:
    ts = datetime.fromtimestamp(m).strftime('%m-%d %H:%M')
    print(f"  [{state}] {t:24s}  ({ts})")
    print(f"          ← {src}")

if not AUTO:
    print()
    try:
        ans = input("적용할까요? [Y/n] ").strip().lower()
    except EOFError:
        ans = 'y'
    if ans and ans not in ('y', 'yes', ''):
        print("취소했습니다.")
        sys.exit(0)

backup = os.path.join(HERE, 'backup', datetime.now().strftime('%Y%m%d_%H%M%S'))
ok = fail = 0
print()
for t, src, state, m in plan:
    dst = os.path.join(HERE, t)
    try:
        if os.path.exists(dst):
            os.makedirs(backup, exist_ok=True)
            shutil.copy2(dst, os.path.join(backup, t))
        shutil.copy2(src, dst)
        print(f"  적용 완료: {t}")
        ok += 1
    except Exception as e:
        print(f"  실패: {t}  ({e})")
        fail += 1

print(f"\n{'-' * 60}")
print(f"완료: {ok}개 적용" + (f", {fail}개 실패" if fail else ""))
if os.path.isdir(backup):
    print(f"기존 파일 백업: {backup}")

if BUILD and ok:
    print("\n대시보드를 다시 생성합니다...")
    r = subprocess.run([sys.executable, os.path.join(HERE, 'build_dashboard.py')],
                       cwd=HERE, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    print("생성 완료" if r.returncode == 0 else "생성 실패 - 위 오류를 확인하세요")
else:
    print("\n다음:  C:/python312/python.exe build_dashboard.py")
