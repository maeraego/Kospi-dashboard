# -*- coding: utf-8 -*-
"""
notify_regime.py  -  레짐이 바뀐 날에만 텔레그램으로 알림

auto_update.bat 의 데이터 수집 단계 뒤에 붙어서 돈다.
점수·백분위·레짐을 build_dashboard 에서 그대로 가져오므로
대시보드 화면과 항상 같은 숫자를 보낸다.

사용법:
  python notify_regime.py           # 레짐이 바뀐 경우에만 발송
  python notify_regime.py --force   # 변화 없어도 현재 상태 발송 (점검용)
  python notify_regime.py --dry     # 발송하지 않고 화면에만 출력

필요:  .env 에 TELEGRAM_TOKEN, MY_TELEGRAM_ID
상태:  regime_state.json 에 직전 레짐을 저장해 변화를 판단
"""
import os, sys, json, io, contextlib, datetime

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'regime_state.json')
DASH_URL = 'https://maeraego.github.io/Kospi-dashboard/'
IDX = [('KOSPI', '코스피'), ('KOSDAQ', '코스닥')]

FORCE = '--force' in sys.argv
DRY = '--dry' in sys.argv


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HERE, '.env'))
    except ImportError:
        print('  ! python-dotenv 미설치 - .env 를 읽지 못함')
    return os.environ.get('TELEGRAM_TOKEN'), os.environ.get('MY_TELEGRAM_ID')


def current_scores():
    """build_dashboard 를 import 해서 화면과 동일한 점수를 얻는다.

    build_dashboard 는 모듈 최상단에서 dashboard.html 까지 생성하므로
    출력만 삼키고 그대로 쓴다 (로컬 html 도 덩달아 최신화된다).
    """
    sys.path.insert(0, HERE)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import build_dashboard as bd
    out = {}
    for key, label in IDX:
        a = bd.analyze(key)
        rl, _ = bd.regime(a['pct'])
        out[key] = {'label': label, 'score': float(a['cur']),
                    'pct': float(a['pct']), 'regime': rl}
    return out


def read_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(cur):
    snap = {k: {'regime': v['regime'], 'score': round(v['score'], 4),
                'pct': round(v['pct'], 4)} for k, v in cur.items()}
    snap['_updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)


def build_message(cur, prev, first_run):
    """보낼 메시지를 만든다. 보낼 게 없으면 None."""
    changed = [k for k, _ in IDX
               if prev.get(k, {}).get('regime') not in (None, cur[k]['regime'])]

    if first_run:
        head = '레짐 감시를 시작합니다'
    elif changed:
        head = '레짐 변경'
    elif FORCE:
        head = '현재 레짐 (변화 없음)'
    else:
        return None, changed

    lines = [head, '']
    for key, label in IDX:
        c = cur[key]
        mark = '  ← 변경' if key in changed else ''
        before = prev.get(key, {}).get('regime')
        if key in changed and before:
            lines.append(f'{label}: {before} → {c["regime"]}{mark}')
        else:
            lines.append(f'{label}: {c["regime"]}{mark}')
        lines.append(f'  점수 {c["score"]:+.2f} · 백분위 {c["pct"]*100:.0f}%')
    lines += ['', datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), DASH_URL]
    return '\n'.join(lines), changed


def send(token, chat_id, text):
    import requests
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat_id, 'text': text,
              'disable_web_page_preview': True},
        timeout=20)
    r.raise_for_status()
    return r


def main():
    token, chat_id = load_env()
    if not token or not chat_id:
        print('  ! TELEGRAM_TOKEN / MY_TELEGRAM_ID 없음 - 알림 건너뜀')
        return

    cur = current_scores()
    prev = read_state()
    first_run = not prev

    for key, label in IDX:
        c = cur[key]
        print(f'  {label}: 점수 {c["score"]:+.2f} · '
              f'백분위 {c["pct"]*100:.0f}% · {c["regime"]}')

    text, changed = build_message(cur, prev, first_run)
    if text is None:
        print('  레짐 변화 없음 - 알림 생략')
        write_state(cur)
        return

    print('  ---- 발송 내용 ----')
    print('  ' + text.replace('\n', '\n  '))
    if DRY:
        print('  (--dry: 실제 발송 안 함, 상태도 저장 안 함)')
        return

    send(token, chat_id, text)
    print(f'  텔레그램 발송 완료 (변경 {len(changed)}건)')
    write_state(cur)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # 알림 실패가 데이터 수집 파이프라인을 망가뜨리면 안 된다
        print(f'  ! 알림 실패: {type(e).__name__}: {e}')
    sys.exit(0)
