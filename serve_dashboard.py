# -*- coding: utf-8 -*-
"""
serve_dashboard.py  —  대시보드를 로컬 서버로 띄워 '데이터 최신화' 버튼을 작동시킨다.

사용법:  C:/python312/python.exe serve_dashboard.py
         (브라우저가 자동으로 열립니다. 끄려면 이 콘솔에서 Ctrl+C)

버튼을 누르면 서버가 백그라운드로 아래를 실행하고 진행 상황을 실시간으로 보낸다:
   update_all.py  →  (순이익/예상PER 입력이 있으면) update_fwd_per.py  →  build_dashboard.py

설계 메모:
  · ThreadingHTTPServer 를 쓴다. 단일 스레드면 갱신하는 동안 서버가 다른 요청을
    전혀 못 받아 화면이 멈춘 것처럼 보인다. (이전 버전의 '반응 없음' 원인)
  · 갱신은 별도 스레드에서 돌리고 POST 는 즉시 응답한다.
    브라우저는 /api/progress 를 주기적으로 물어 진행 로그를 받아간다.
  · 수집기 출력을 한 줄씩 흘려보내므로 몇 분 걸리는 작업도 진행이 눈에 보인다.

HTML을 그냥 더블클릭해 열면(file://) 브라우저 보안 때문에 버튼이 동작하지 않는다.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
PY = sys.executable

JOB = {'running': False, 'step': '', 'log': [], 'done': False, 'ok': False, 'started_at': 0.0}
LOCK = threading.Lock()


def emit(line):
    """진행 로그 한 줄 기록 (콘솔에도 출력)."""
    line = line.rstrip()
    with LOCK:
        JOB['log'].append(line)
        if len(JOB['log']) > 2000:
            del JOB['log'][:500]
    try:
        print(line)
    except Exception:
        pass


def run_stream(script, *args, label=None):
    """스크립트를 실행하며 출력을 한 줄씩 흘려보낸다 → 성공 여부."""
    path = os.path.join(HERE, script)
    if not os.path.exists(path):
        emit(f"[없음] {script} - 건너뜁니다")
        return False
    with LOCK:
        JOB['step'] = label or script
    emit("")
    emit(f"── {label or script} ──")
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    try:
        p = subprocess.Popen([PY, path, *args], cwd=HERE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding='utf-8', errors='replace',
                             env=env, bufsize=1)
    except Exception as e:
        emit(f"[실행 실패] {script}: {e}")
        return False
    for line in p.stdout:
        emit(line)
    p.wait()
    if p.returncode != 0:
        emit(f"[실패] {script} (종료코드 {p.returncode})")
        return False
    return True


def do_update(fwd, ni1, ni2):
    with LOCK:
        JOB.update(running=True, done=False, ok=False, log=[], step='시작',
                   started_at=time.time())
    ok = True
    emit("데이터 최신화를 시작합니다.")
    emit("KRX를 과거 연도부터 받는 경우 수 분이 걸릴 수 있습니다.")

    ok &= run_stream('update_all.py', label='데이터 수집')

    if ni1 or ni2:
        prev1 = prev2 = None
        try:
            import csv as _csv
            with open(os.path.join(HERE, 'fwd_ni.csv'), encoding='utf-8') as f:
                rows = list(_csv.DictReader(f))
            if rows:
                prev1, prev2 = rows[-1].get('FY1'), rows[-1].get('FY2')
        except Exception:
            pass
        a1, a2 = (ni1 or prev1 or ''), (ni2 or prev2 or '')
        try:
            float(a1); float(a2)
            ok &= run_stream('update_fwd_per.py', '--ni', a1, a2, label='예상순이익 반영')
        except (ValueError, TypeError):
            emit(f"[건너뜀] 예상순이익: 숫자가 아니거나 기존값 없음 ('{ni1}' '{ni2}')")
    elif fwd:
        try:
            float(fwd)
            ok &= run_stream('update_fwd_per.py', fwd, label='예상PER 반영')
        except ValueError:
            emit(f"[건너뜀] 예상PER: 숫자가 아님 ({fwd})")
    else:
        emit("")
        emit("── 예상순이익 ── 입력값 없음 (기존 값 유지)")

    ok &= run_stream('build_dashboard.py', label='대시보드 생성')
    # 계절성 대시보드는 별개 파일이라 같이 갱신해 준다(실패해도 메인엔 영향 없음).
    run_stream('season_dashboard.py', label='계절성 대시보드 생성')

    took = time.time() - JOB['started_at']
    emit("")
    emit(f"{'완료' if ok else '오류로 종료'} - {took:.0f}초 소요")
    with LOCK:
        JOB.update(running=False, done=True, ok=ok, step='완료' if ok else '오류')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()

    def do_GET(self):
        if self.path.startswith('/api/ping'):
            return self._json({'ok': True})
        if self.path.startswith('/api/progress'):
            with LOCK:
                return self._json({
                    'running': JOB['running'], 'done': JOB['done'], 'ok': JOB['ok'],
                    'step': JOB['step'], 'log': '\n'.join(JOB['log']),
                    'elapsed': int(time.time() - JOB['started_at']) if JOB['started_at'] else 0,
                })
        if self.path in ('/', ''):
            self.path = '/dashboard.html'
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith('/api/update'):
            return self._json({'ok': False, 'log': 'unknown endpoint'}, 404)
        with LOCK:
            if JOB['running']:
                return self._json({'started': False, 'busy': True})
        fwd = ni1 = ni2 = ''
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if n:
                b = json.loads(self.rfile.read(n).decode('utf-8'))
                fwd = str(b.get('fwd_per', '')).strip()
                ni1 = str(b.get('ni_fy1', '')).strip()
                ni2 = str(b.get('ni_fy2', '')).strip()
        except Exception:
            pass
        threading.Thread(target=do_update, args=(fwd, ni1, ni2), daemon=True).start()
        return self._json({'started': True})


def main():
    if not os.path.exists(os.path.join(HERE, 'dashboard.html')):
        print("[안내] dashboard.html 이 없습니다. 먼저 만듭니다...")
        subprocess.run([PY, os.path.join(HERE, 'build_dashboard.py')], cwd=HERE)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/dashboard.html"
    print("=" * 56)
    print(f"  대시보드 서버 실행 중 -> {url}")
    print("  종료하려면 이 창에서 Ctrl+C")
    print("=" * 56)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
        srv.shutdown()


if __name__ == '__main__':
    main()
