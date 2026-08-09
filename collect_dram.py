# -*- coding: utf-8 -*-
"""
collect_dram.py  -  반도체 메모리 가격·금액·물량 수집

세 갈래로 모은다.

 (1) ECOS 수출물가지수 (월간, 1971~)      -> dram_monthly.parquet
     한국은행 공식. 삼성·SK하이닉스가 실제로 받는 수출단가 지수라
     한국 주식 관점에서는 글로벌 스팟보다 오히려 직접적이다.
       402Y016/30911201AA  DRAM
       402Y016/30911202AA  플래시메모리
       402Y016/30911203AA  시스템반도체
       402Y014/30911AA     반도체(전체)

 (2) ECOS 수출 금액/물량지수 (월간, 2000~) -> 같은 parquet 에 합침
       403Y001/30911AA     반도체 수출금액지수
       403Y002/30911AA     반도체 수출물량지수
       403Y001/309112AA    집적회로 수출금액지수
       403Y002/309112AA    집적회로 수출물량지수
     주의: 절대 달러금액이 아니라 지수(2020=100)다.
           절대금액이 필요하면 관세청 무역통계 API(별도 무료키)를 붙여야 한다.

 (3) TrendForce 공개 스팟/컨트랙트 (누적)  -> dram_spot_weekly.parquet
                                            dram_contract.parquet
     과거 시계열은 유료라 살 수 없다. 그래서 '현재 값'을 주기적으로 받아
     직접 시계열을 쌓는다. 처음엔 점 몇 개지만 시간이 지나면 주봉이 된다.
     실패해도 (1)(2)에는 영향 없음.

사용법:  C:/python312/python.exe collect_dram.py
필요:    .env 의 ECOS_KEY
"""
import os, sys, json, time, urllib.request, datetime
import pandas as pd

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHLY = os.path.join(HERE, 'dram_monthly.parquet')
SPOT = os.path.join(HERE, 'dram_spot_weekly.parquet')
CONTRACT = os.path.join(HERE, 'dram_contract.parquet')

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, '.env'))
except ImportError:
    pass

BASE = 'https://ecos.bok.or.kr/api'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# 라벨 -> (통계표코드, 항목코드, 시작연월)
ECOS_ITEMS = {
    'DRAM수출물가':      ('402Y016', '30911201AA', '197101'),
    '플래시수출물가':     ('402Y016', '30911202AA', '200001'),
    '시스템반도체수출물가': ('402Y016', '30911203AA', '199001'),
    '반도체수출물가':     ('402Y014', '30911AA',    '197101'),
    '반도체수출금액지수':   ('403Y001', '30911AA',    '200001'),
    '반도체수출물량지수':   ('403Y002', '30911AA',    '200001'),
    '집적회로수출금액지수': ('403Y001', '309112AA',   '200001'),
    '집적회로수출물량지수': ('403Y002', '309112AA',   '200001'),
}


def _get(url, retries=4):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(last)


def collect_ecos():
    key = os.environ.get('ECOS_KEY')
    if not key:
        print('  [중단] ECOS_KEY 없음 - .env 확인')
        return None
    end = datetime.date.today().strftime('%Y%m')
    out = {}
    for label, (stat, item, start) in ECOS_ITEMS.items():
        url = (f'{BASE}/StatisticSearch/{key}/json/kr/1/100000/'
               f'{stat}/M/{start}/{end}/{item}')
        try:
            rows = _get(url).get('StatisticSearch', {}).get('row', [])
        except Exception as e:
            print(f'  x {label:18s} 조회 실패: {e}')
            continue
        if not rows:
            print(f'  x {label:18s} 데이터 없음')
            continue
        s = pd.Series({r['TIME']: float(r['DATA_VALUE'])
                       for r in rows if r.get('DATA_VALUE') not in (None, '')})
        s.index = pd.to_datetime(s.index, format='%Y%m')
        out[label] = s.sort_index()
        print(f'  · {label:18s} {s.index[0].date()}~{s.index[-1].date()}'
              f'  n={len(s):4d}  최근={s.iloc[-1]:.2f}')
    if not out:
        return None
    df = pd.DataFrame(out).sort_index()
    df.to_parquet(MONTHLY)
    print(f'  -> {os.path.basename(MONTHLY)} 저장 ({len(df)}행 x {len(df.columns)}열)')
    return df


def _scrape_trendforce():
    """TrendForce 가격 페이지를 한 번 받아 스팟/컨트랙트를 나눠 뽑는다.

    /dram_spot 과 /dram_contract 는 실제로 같은 HTML 을 준다.
    그래서 URL 이 아니라 '표 헤더'로 구분해야 한다.
        Daily High / Weekly High 가 있으면  -> 스팟
        Average Change 가 있으면            -> 컨트랙트
    값은 항상 'Session Average' 열을 쓴다(헤더 이름으로 위치를 찾는다).
    """
    import requests
    from bs4 import BeautifulSoup
    r = requests.get('https://www.trendforce.com/price/dram/dram_spot',
                     timeout=25, headers=UA)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    spot, contract = {}, {}
    for tb in soup.find_all('table'):
        hdr = [th.get_text(strip=True) for th in tb.find_all('th')]
        if not hdr or 'Item' not in hdr:
            continue
        if any(h in ('Daily High', 'Weekly High') for h in hdr):
            target = spot
        elif any('Change' in h for h in hdr):
            target = contract
        else:
            continue
        try:
            col = hdr.index('Session Average')
        except ValueError:
            continue

        for tr in tb.find_all('tr'):
            tds = [td.get_text(strip=True) for td in tr.find_all('td')]
            if len(tds) <= col:
                continue
            name = tds[0]
            v = tds[col].replace('$', '').replace(',', '').strip()
            try:
                target[name] = float(v)
            except ValueError:
                continue
    return spot, contract


def _accumulate(rec, path, kind):
    if not rec:
        print(f'  x {kind} 파싱 결과 없음 - 페이지 구조가 바뀌었을 수 있음')
        return None
    today = pd.Timestamp(datetime.date.today())
    new = pd.DataFrame([rec], index=[today])
    if os.path.exists(path):
        old = pd.read_parquet(path)
        df = pd.concat([old[~old.index.isin(new.index)], new]).sort_index()
    else:
        df = new
    df.to_parquet(path)
    print(f'  · {kind} {len(rec)}개 품목 기록 -> 누적 {len(df)}회분')
    for k, v in list(rec.items())[:8]:
        print(f'      {k[:44]:44s} ${v}')
    return df


def collect_trendforce():
    try:
        spot, contract = _scrape_trendforce()
    except Exception as e:
        print(f'  x TrendForce 수집 실패(무시 가능): {e}')
        return None, None
    return (_accumulate(spot, SPOT, '스팟'),
            _accumulate(contract, CONTRACT, '컨트랙트'))


if __name__ == '__main__':
    print('=' * 60)
    print('> ECOS 수출물가/금액/물량 지수 (월간)')
    print('=' * 60)
    collect_ecos()
    print()
    print('=' * 60)
    print('> TrendForce 스팟/컨트랙트 (누적)')
    print('=' * 60)
    collect_trendforce()
