# -*- coding: utf-8 -*-
"""
collect_customs.py  -  관세청 품목별 수출입실적 (실제 달러금액·중량)

ECOS 는 지수(2020=100)만 준다. 절대 금액이 필요해서 관세청을 붙인다.
  수출 신고미화금액(USD) · 수입 과세가격미화금액(USD) · 순중량(kg)

대상 HS부호 (6단위)
  854232  메모리(DRAM 포함)      <- 핵심
  854231  프로세서와 컨트롤러
  854233  증폭기
  854239  기타 집적회로

필요:  .env 의 CUSTOMS_KEY
       https://www.data.go.kr/data/15101609/openapi.do 에서 무료 발급(자동승인)

사용법:
  python collect_customs.py --probe   # 응답 원문을 그대로 출력(규격 확인용)
  python collect_customs.py           # 수집 -> customs_monthly.parquet

주의: 엔드포인트/파라미터 이름은 유니패스 연계가이드 기준으로 넣어두었다.
      키를 받은 뒤 --probe 로 실제 응답을 한 번 확인하고 맞추는 것이 안전하다.
      응답이 비면 PARAM_* 상수만 고치면 된다.
"""
import os, sys, datetime
import xml.etree.ElementTree as ET
import pandas as pd

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'customs_monthly.parquet')
PROBE = '--probe' in sys.argv

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, '.env'))
except ImportError:
    pass

# 공공데이터포털(data.go.kr) 경유 엔드포인트.
# 후보를 실제로 찔러 확인했다 - 이 경로만 403(키 문제)을 주고
# 나머지는 400 NO_OPENAPI_SERVICE_ERROR 라 경로 자체가 없다.
ENDPOINT = 'https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList'
PARAM_KEY = 'serviceKey'  # 인증키 (일반 인증키 Decoding 값)
PARAM_HS = 'hsSgn'        # HS부호
PARAM_FROM = 'strtYymm'   # 시작 연월
PARAM_TO = 'endYymm'      # 종료 연월

HS_CODES = {
    '854232': '메모리(DRAM)',
    '854231': '프로세서·컨트롤러',
    '854233': '증폭기',
    '854239': '기타집적회로',
}

# 응답 태그 후보 (연계가이드 표기 흔들림에 대비해 여러 이름을 본다)
F_PERIOD = ('year', 'yyyymm', 'basYymm', 'prid')
F_EXP_USD = ('expDlr', 'expUsdAmt', 'expAmt')
F_IMP_USD = ('impDlr', 'impUsdAmt', 'impAmt')
F_EXP_WGT = ('expWgt', 'expNtwg')
F_IMP_WGT = ('impWgt', 'impNtwg')


def _safe(e):
    """예외 메시지에 인증키가 섞여 나오지 않도록 가린다.

    requests 의 HTTPError 는 요청 URL 을 통째로 담기 때문에
    그대로 로그에 쓰면 키가 평문으로 남는다.
    """
    import re
    return re.sub(r'(crkyCn|serviceKey)=[^&\s]+', r'\1=<REDACTED>',
                  f'{type(e).__name__}: {e}')


def _pick(node, names):
    for n in names:
        e = node.find(n)
        if e is not None and (e.text or '').strip():
            return e.text.strip()
    return None


def fetch(hs, start, end, key):
    """data.go.kr 은 Encoding/Decoding 두 형태의 키를 준다.
    Encoding 키를 그대로 params 에 넣으면 requests 가 한 번 더 인코딩해
    %252F 처럼 이중 인코딩되므로, % 가 있으면 먼저 풀어서 넘긴다."""
    import requests, urllib.parse, re
    if '%' in key:
        key = urllib.parse.unquote(key)
    params = {PARAM_KEY: key, PARAM_HS: hs, PARAM_FROM: start, PARAM_TO: end}
    r = requests.get(ENDPOINT, params=params, timeout=40)
    r.raise_for_status()
    # 포털은 오류도 200 으로 주는 경우가 있어 본문을 확인한다
    m = re.search(r'<errMsg>([^<]*)</errMsg>', r.text)
    if m:
        auth = re.search(r'<returnAuthMsg>([^<]*)</returnAuthMsg>', r.text)
        raise RuntimeError(f'{m.group(1)} / {auth.group(1) if auth else ""}')
    return r.text


def parse(xml_text, hs, label):
    root = ET.fromstring(xml_text)
    rows = []
    # 반복 노드 이름이 가이드마다 달라 자식 중 기간 필드를 가진 것을 찾는다
    for node in root.iter():
        if node is root:
            continue
        period = _pick(node, F_PERIOD)
        if not period:
            continue
        def num(names):
            v = _pick(node, names)
            if v is None:
                return None
            try:
                return float(str(v).replace(',', ''))
            except ValueError:
                return None
        rec = {
            'period': period,
            'hs': hs,
            'item': label,
            'export_usd': num(F_EXP_USD),
            'import_usd': num(F_IMP_USD),
            'export_kg': num(F_EXP_WGT),
            'import_kg': num(F_IMP_WGT),
        }
        if rec['export_usd'] is not None or rec['import_usd'] is not None:
            rows.append(rec)
    return rows


def main():
    key = os.environ.get('CUSTOMS_KEY')
    if not key:
        print('  [중단] CUSTOMS_KEY 없음')
        print('    https://www.data.go.kr/data/15101609/openapi.do 에서 무료 발급 후')
        print('    .env 에  CUSTOMS_KEY=발급키  한 줄을 추가하세요.')
        return

    today = datetime.date.today()
    end = today.strftime('%Y%m')
    start = f'{today.year - 5}{today.month:02d}'

    if PROBE:
        print(f'  [probe] {ENDPOINT}')
        print(f'  [probe] {PARAM_HS}=854232 {PARAM_FROM}={start} {PARAM_TO}={end}')
        try:
            txt = fetch('854232', start, end, key)
        except Exception as e:
            print(f'  x 요청 실패: {_safe(e)}')
            return
        print('  ---- 응답 원문 앞부분 ----')
        print(txt[:2500])
        return

    allrows = []
    for hs, label in HS_CODES.items():
        try:
            rows = parse(fetch(hs, start, end, key), hs, label)
        except Exception as e:
            print(f'  x {label:16s} 실패: {_safe(e)}')
            continue
        if not rows:
            print(f'  x {label:16s} 파싱 0건 - --probe 로 응답 확인 필요')
            continue
        allrows += rows
        print(f'  · {label:16s} {len(rows)}건  {rows[0]["period"]}~{rows[-1]["period"]}')

    if not allrows:
        print('  수집된 행이 없습니다. --probe 로 실제 응답 구조를 확인하세요.')
        return
    df = pd.DataFrame(allrows).drop_duplicates(['period', 'hs'])
    df.to_parquet(OUT, index=False)
    print(f'  -> {os.path.basename(OUT)} 저장 ({len(df)}행)')

    mem = df[df['hs'] == '854232'].sort_values('period')
    if len(mem):
        last = mem.iloc[-1]
        print(f'  메모리 최근({last["period"]}) '
              f'수출 ${last["export_usd"]:,.0f} / {last["export_kg"]:,.0f}kg')


if __name__ == '__main__':
    print('=' * 60)
    print('> 관세청 품목별 수출입실적')
    print('=' * 60)
    try:
        main()
    except Exception as e:
        print(f'  ! 실패: {_safe(e)}')
    sys.exit(0)
