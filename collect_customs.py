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

# 공공데이터포털 '품목별 국가별 수출입실적'.
# 실제 호출로 확인한 경로다. cntyCd(국가코드)는 생략 가능하며,
# 생략하면 전체 국가 합계를 월별로 준다.
ENDPOINT = 'https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList'
PARAM_KEY = 'serviceKey'  # 인증키 (Encoding 값이면 unquote 후 전달)
PARAM_HS = 'hsSgn'        # HS부호(6단위)
PARAM_FROM = 'strtYymm'   # 시작 연월
PARAM_TO = 'endYymm'      # 종료 연월

YEARS_BACK = 5   # 이 API 는 1회 조회가 1년으로 제한되어 연 단위로 반복한다

HS_CODES = {
    '854232': '메모리(DRAM)',
    '854231': '프로세서·컨트롤러',
    '854233': '증폭기',
    '854239': '기타집적회로',
}

# 실제 응답 필드 (호출로 확인)
#   year=2026.01 / statKor=디램 / hsCode=8542321010
#   expDlr expWgt impDlr impWgt balPayments
# year='총계' 인 합계행이 섞여 오므로 반드시 걸러야 한다.


def _safe(e):
    """예외 메시지에 인증키가 섞여 나오지 않도록 가린다.

    requests 의 HTTPError 는 요청 URL 을 통째로 담기 때문에
    그대로 로그에 쓰면 키가 평문으로 남는다.
    """
    import re
    return re.sub(r'(crkyCn|serviceKey)=[^&\s]+', r'\1=<REDACTED>',
                  f'{type(e).__name__}: {e}')


def _txt(node, name):
    e = node.find(name)
    return (e.text or '').strip() if e is not None else ''


def _num(node, name):
    v = _txt(node, name).replace(',', '')
    try:
        return float(v)
    except ValueError:
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
    # 포털은 오류도 200 으로 준다. 게다가 오류 위치가 두 군데다.
    #   인증/서비스 오류 -> <errMsg>
    #   파라미터 오류    -> <resultMsg>  (예: 조회기간 1년 초과)
    # resultMsg 를 안 보면 0건을 '데이터 없음'으로 오해하게 된다.
    m = re.search(r'<errMsg>([^<]*)</errMsg>', r.text)
    if m:
        auth = re.search(r'<returnAuthMsg>([^<]*)</returnAuthMsg>', r.text)
        raise RuntimeError(f'{m.group(1)} / {auth.group(1) if auth else ""}')
    rm = re.search(r'<resultMsg>([^<]*)</resultMsg>', r.text)
    if rm and '정상' not in rm.group(1):
        raise RuntimeError(rm.group(1))
    return r.text


def parse(xml_text, hs, label):
    """<item> 들을 월별 레코드로. 6단위 아래 10단위 세부품목이 여러 개 오므로
    같은 달끼리 합산한다. year='총계' 인 합계행은 버린다(중복 계상 방지)."""
    root = ET.fromstring(xml_text)
    acc = {}
    for node in root.findall('.//item'):
        period = _txt(node, 'year')          # '2026.01' 또는 '총계'
        if not period or '.' not in period:
            continue
        period = period.replace('.', '-')    # 2026-01
        a = acc.setdefault(period, {
            'period': period, 'hs': hs, 'item': label,
            'export_usd': 0.0, 'import_usd': 0.0,
            'export_kg': 0.0, 'import_kg': 0.0, 'subitems': 0})
        for key, tag in (('export_usd', 'expDlr'), ('import_usd', 'impDlr'),
                         ('export_kg', 'expWgt'), ('import_kg', 'impWgt')):
            v = _num(node, tag)
            if v is not None:
                a[key] += v
        a['subitems'] += 1
    return sorted(acc.values(), key=lambda r: r['period'])


def main():
    key = os.environ.get('CUSTOMS_KEY')
    if not key:
        print('  [중단] CUSTOMS_KEY 없음')
        print('    https://www.data.go.kr/data/15101609/openapi.do 에서 무료 발급 후')
        print('    .env 에  CUSTOMS_KEY=발급키  한 줄을 추가하세요.')
        return

    today = datetime.date.today()
    start, end = f'{today.year}01', today.strftime('%Y%m')

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

    # 이 API 는 조회기간을 1년 이내로 제한한다. 연 단위로 쪼개 호출한다.
    years = list(range(today.year - YEARS_BACK, today.year + 1))
    allrows = []
    for hs, label in HS_CODES.items():
        rows, failed = [], 0
        for y in years:
            s, e = f'{y}01', f'{y}12'
            try:
                rows += parse(fetch(hs, s, e, key), hs, label)
            except Exception as ex:
                failed += 1
                if failed == 1:
                    print(f'  x {label:16s} {y}년 실패: {_safe(ex)}')
        if not rows:
            print(f'  x {label:16s} 0건 - --probe 로 응답 확인 필요')
            continue
        rows.sort(key=lambda r: r['period'])
        allrows += rows
        print(f'  · {label:16s} {len(rows):3d}개월  '
              f'{rows[0]["period"]}~{rows[-1]["period"]}')

    if not allrows:
        print('  수집된 행이 없습니다. --probe 로 실제 응답 구조를 확인하세요.')
        return
    df = pd.DataFrame(allrows).drop_duplicates(['period', 'hs'])
    df.to_parquet(OUT, index=False)
    print(f'  -> {os.path.basename(OUT)} 저장 ({len(df)}행)')

    mem = df[df['hs'] == '854232'].sort_values('period')
    if len(mem):
        r = mem.iloc[-1]
        print(f'  메모리 최근 {r["period"]}  '
              f'수출 ${r["export_usd"]/1e8:,.1f}억 / {r["export_kg"]/1000:,.0f}톤')
        if len(mem) >= 13:
            p12 = mem.iloc[-13]
            print(f'    전년동월비  금액 {(r["export_usd"]/p12["export_usd"]-1)*100:+.1f}% '
                  f'· 물량 {(r["export_kg"]/p12["export_kg"]-1)*100:+.1f}%')
            up = (r['export_usd']/r['export_kg']) / (p12['export_usd']/p12['export_kg']) - 1
            print(f'    kg당 단가   {r["export_usd"]/r["export_kg"]:,.0f} $/kg  ({up*100:+.1f}% YoY)')


if __name__ == '__main__':
    print('=' * 60)
    print('> 관세청 품목별 수출입실적')
    print('=' * 60)
    try:
        main()
    except Exception as e:
        print(f'  ! 실패: {_safe(e)}')
    sys.exit(0)
