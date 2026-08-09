# -*- coding: utf-8 -*-
"""
collect_openrouter.py  -  OpenRouter 회사별 토큰 사용량 수집

OpenRouter 랭킹 페이지가 내부적으로 쓰는 API 에서 모델별 토큰을 받아
회사(= permaslug 의 앞부분)별로 합산해 스냅샷으로 쌓는다.

  https://openrouter.ai/api/frontend/v1/rankings/models?view=month

주의 - 두 가지 한계를 알고 써야 한다.
 1) 이 API 는 '최근 1개월 누적' 스냅샷 하나만 준다. 과거 시계열은 주지 않는다.
    그래서 실행할 때마다 한 줄씩 쌓아 직접 시계열을 만든다.
 2) /api/frontend/ 는 문서화된 공개 API 가 아니라 웹사이트 내부용이다.
    예고 없이 바뀔 수 있으므로 실패해도 조용히 넘어가고 로그만 남긴다.

저장: openrouter_monthly.parquet  (long format)
      snapshot | company | tokens | prompt_tokens | completion_tokens | requests | models

사용법:  C:/python312/python.exe collect_openrouter.py
"""
import os, sys, datetime, collections
import pandas as pd

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'openrouter_monthly.parquet')
API = 'https://openrouter.ai/api/frontend/v1/rankings/models?view=month'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      'Accept': 'application/json'}


def fetch():
    import requests
    r = requests.get(API, timeout=40, headers=UA)
    r.raise_for_status()
    rows = r.json().get('data') or []
    if not rows:
        raise RuntimeError('data 비어 있음 - API 구조가 바뀌었을 수 있음')
    return rows


def aggregate(rows):
    """모델 단위 레코드를 회사 단위로 합산."""
    tok = collections.Counter()
    ptok = collections.Counter()
    ctok = collections.Counter()
    req = collections.Counter()
    mdl = collections.Counter()
    for r in rows:
        slug = r.get('model_permaslug') or ''
        company = slug.split('/')[0] if '/' in slug else (slug or 'unknown')
        p = r.get('total_prompt_tokens') or 0
        c = r.get('total_completion_tokens') or 0
        ptok[company] += p
        ctok[company] += c
        tok[company] += p + c
        req[company] += r.get('count') or 0
        mdl[company] += 1
    # 스냅샷 기준일: 응답에 실린 date 중 가장 최근
    dates = [str(r.get('date') or '')[:10] for r in rows if r.get('date')]
    asof = max(dates) if dates else datetime.date.today().isoformat()
    return asof, tok, ptok, ctok, req, mdl


def save(asof, tok, ptok, ctok, req, mdl):
    snap = pd.Timestamp(asof)
    df = pd.DataFrame({
        'snapshot': snap,
        'company': list(tok.keys()),
        'tokens': [tok[c] for c in tok],
        'prompt_tokens': [ptok[c] for c in tok],
        'completion_tokens': [ctok[c] for c in tok],
        'requests': [req[c] for c in tok],
        'models': [mdl[c] for c in tok],
    })
    if os.path.exists(OUT):
        old = pd.read_parquet(OUT)
        # 같은 기준일이면 덮어쓴다(하루에 여러 번 돌려도 중복 안 쌓임)
        old = old[old['snapshot'] != snap]
        df = pd.concat([old, df], ignore_index=True)
    df = df.sort_values(['snapshot', 'tokens'], ascending=[True, False])
    df.to_parquet(OUT, index=False)
    return df


if __name__ == '__main__':
    print('=' * 60)
    print('> OpenRouter 회사별 토큰 사용량 (최근 1개월 스냅샷)')
    print('=' * 60)
    try:
        rows = fetch()
        asof, tok, ptok, ctok, req, mdl = aggregate(rows)
        df = save(asof, tok, ptok, ctok, req, mdl)
        total = sum(tok.values())
        snaps = df['snapshot'].nunique()
        print(f'  기준일 {asof} · 모델 {len(rows)}개 · 회사 {len(tok)}개')
        print(f'  합계 {total/1e12:,.1f}조 토큰')
        print(f'  -> {os.path.basename(OUT)} 저장 (누적 스냅샷 {snaps}회)')
        print()
        print(f'  {"회사":16s} {"토큰(조)":>9s} {"점유율":>7s} {"모델":>5s}')
        for c, v in tok.most_common(10):
            print(f'  {c:16s} {v/1e12:9.2f} {v/total*100:6.1f}% {mdl[c]:5d}')
    except Exception as e:
        print(f'  x 수집 실패: {type(e).__name__}: {e}')
        print('    (내부 API라 구조가 바뀌었을 수 있습니다)')
    sys.exit(0)
