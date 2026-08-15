# -*- coding: utf-8 -*-
"""
build_dashboard.py  —  WeightSum 국면 대시보드 (코스피·코스닥 분리)
  각 지수를 자기 신호·자기 가중치·자기 기대수익으로 독립 산출.
사용법:  C:/python312/python.exe build_dashboard.py
입력:    krx_monthly.parquet, krx_daily.parquet, ecos_monthly.parquet,
         fred_monthly.parquet, (선택) fwd_per_monthly.parquet
출력:    dashboard.html
"""
import os, sys, json
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

# 윈도우 cp949 콘솔 대응
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

REQUIRED = ['krx_monthly.parquet', 'krx_daily.parquet',
            'ecos_monthly.parquet', 'fred_monthly.parquet']
_missing = [f for f in REQUIRED if not os.path.exists(os.path.join(HERE, f))]
if _missing:
    print("[중단] 다음 데이터 파일이 이 폴더에 없습니다:")
    for f in _missing:
        print(f"    - {f}")
    print(f"\n  현재 폴더: {HERE}")
    print("\n  해결 방법:")
    print("   1) 수집 스크립트(collect_krx.py / collect_ecos.py / collect_fred.py)와")
    print("      생성된 parquet 파일이 모두 이 폴더에 있어야 합니다.")
    print("   2) 다른 폴더(예: C:\\python312)에서 수집을 돌렸다면,")
    print("      그 폴더의 collect_*.py 와 *.parquet 파일을 이 폴더로 옮기세요.")
    print("   3) 그다음 다시 실행:  python update_all.py")
    sys.exit(1)

def load(n): return pd.read_parquet(os.path.join(HERE, n))

# ── 계절성(핼러윈 효과) 코어 ──
#   "5~10월 지옥 / 11~4월 천국"은 실측으로 사실이지만(코스피 p=0.022, 코스닥 p=0.001),
#   이 대시보드의 예측지평은 12개월이라 계절성이 정의상 상쇄된다(진입월별 12개월 수익 p=0.76·0.93).
#   그래서 종합점수에는 넣지 않고, ① 참고 오버레이 패널 ② 켈리 진입 타이밍 조정으로만 쓴다.
#   season_core 가 없거나 깨져도 메인 대시보드는 그대로 나와야 한다.
try:
    import season_core as SEA
    HAS_SEASON = True
except Exception as _e:                     # noqa: BLE001
    SEA, HAS_SEASON = None, False
    print(f'[경고] season_core 로드 실패 — 계절 오버레이를 건너뜁니다: {_e}')

# ── 원천별 로드 + 출처 귀속 추적 ──
SRC_META = [
    ('krx_monthly.parquet',  'KRX 한국거래소',        'pykrx'),
    ('ecos_monthly.parquet', 'ECOS 한국은행',         'ecos.bok.or.kr Open API'),
    ('fred_monthly.parquet', 'FRED 세인트루이스 연준', 'fred.stlouisfed.org API'),
]
COL_SRC, FILE_INFO = {}, []
_parts = []
for _fn, _label, _api in SRC_META:
    _p = os.path.join(HERE, _fn)
    _t = load(_fn)
    for _c in _t.columns: COL_SRC[_c] = _label
    _parts.append(_t)
    FILE_INFO.append((_label, _api, _fn,
                      pd.Timestamp(os.path.getmtime(_p), unit='s', tz='UTC')
                        .tz_convert('Asia/Seoul').strftime('%Y-%m-%d %H:%M')))
df = _parts[0].join(_parts[1], how='outer').join(_parts[2], how='outer').sort_index()
# ── 데이터 위생 ──
# (1) 0으로 나눈 무한대 제거(예: PER=0 인 달의 파생 ROE=inf)
df = df.replace([np.inf, -np.inf], np.nan)
# (2) '0이 될 수 없는' 지표의 0은 결측 표기이므로 NaN 처리.
#     PER/PBR/종가/시총이 0이면 그 값 자체가 틀릴 뿐 아니라, expanding 평균·표준편차를
#     오염시켜 이후 모든 달의 z-score가 밀린다(실측 최대 2.25σ 왜곡).
#     반면 스프레드·금리차·YoY 변화율은 0이 정상값이므로 건드리지 않는다.
_NONZERO = [c for c in df.columns
            if any(k in c for k in ('_PER', '_PBR', '_ROE', '_종가', '_시총'))]
for _c in _NONZERO:
    df[_c] = df[_c].replace(0, np.nan)

# 지수별 실현변동성(20일, 연율화 %) — VKOSPI 대용
_d = load('krx_daily.parquet').replace([np.inf, -np.inf], np.nan)
for _c in [c for c in _d.columns
           if any(k in c for k in ('_PER', '_PBR', '_ROE', '_종가', '_시총'))]:
    _d[_c] = _d[_c].replace(0, np.nan)
# ── 최신 월의 시가총액·종가·PER·PBR을 '오늘(최신 거래일)' 일별값으로 덮어쓴다 ──
#   월별 parquet의 마지막 행은 지난 월말 값이라, 그대로 쓰면 지수가 매일 움직여도
#   시총·예상PER·시총/M2 등이 한 달에 한 번만 바뀐다. 일별 최신값을 이번 달에 반영해
#   매 거래일 갱신되게 한다. (과거 달은 건드리지 않는다)
for _ix in ('KOSPI', 'KOSDAQ'):
    for _suf in ('_종가', '_시총', '_PER', '_PBR'):
        _col = f'{_ix}{_suf}'
        if _col in _d.columns and _col in df.columns:
            _s = _d[_col].dropna()
            if len(_s):
                _last = _s.index[-1]
                _mkey = _last.to_period('M').to_timestamp('M')
                if _mkey in df.index or _mkey >= df.index.min():
                    df.loc[_mkey, _col] = float(_s.iloc[-1])
df = df.sort_index()
for ix in ('KOSPI', 'KOSDAQ'):
    df[f'{ix}_변동성'] = (np.log(_d[f'{ix}_종가']).diff().rolling(20).std()
                        * np.sqrt(252) * 100).resample('ME').last()
    COL_SRC[f'{ix}_변동성'] = '파생 (KRX 일별에서 산출)'

# 예상PER(Forward, 코스피 전용) — 차트 복원본 있으면 사용
try:
    _f = load('fwd_per_monthly.parquet')['예상PER'].dropna()
    # df 인덱스는 KRX 기준(보통 2005~)이라, 그냥 대입하면 그 이전 구간이 잘려나간다.
    # 예상PER이 더 오래된 경우 df 인덱스를 먼저 확장해 전 기간을 보존한다.
    if len(_f) and _f.index.min() < df.index.min():
        df = df.reindex(df.index.union(_f.index)).sort_index()
    df['예상PER'] = _f; HAS_FPE = True; FPE_ASOF = _f.index[-1]
    COL_SRC['예상PER'] = '수동 입력 (애널리스트 컨센서스)'
    FILE_INFO.append(('수동 입력', 'update_fwd_per.py', 'fwd_per_monthly.parquet',
                      pd.Timestamp(os.path.getmtime(os.path.join(HERE, 'fwd_per_monthly.parquet')),
                                   unit='s', tz='UTC').tz_convert('Asia/Seoul').strftime('%Y-%m-%d %H:%M')))
except Exception:
    HAS_FPE = False; FPE_ASOF = None

# ── 신용융자/예탁금 (금융투자협회 FreeSIS, 코스피 전용) ──
#   빚내서 산 돈(신용융자) ÷ 대기 현금(고객예탁금) = 투자자 레버리지.
#   기존 14개 신호는 밸류·금리·환율·경기·변동성만 재고 '레버리지'를 재는 게 없어,
#   기존 신호와의 평균절대상관이 0.183(최대 0.390, 일드갭)으로 낮다. 상관벌점을
#   거의 안 맞아 단독 IC 0.368 대비 가중을 후하게 받는다(8%대, 14개 중 5위).
#   실측 표본외 IC: 분할 5개 중 4개 개선, 평균 +0.035 (2012~2018년 분할에서 +0.04~0.06).
#   코스닥은 평균 +0.002로 노이즈 수준이라 넣지 않는다(2020년 분할에선 오히려 악화).
#   [T+1 공표] 자금 수치는 다음 영업일에 공표된다. 월말 시점에 실제로 알 수 있는 값은
#     전 영업일치이므로 일별에서 shift(1) 한 뒤 월말을 뽑는다. 이 보정이 없으면
#     월말 종가와 같은 날 자금을 쓰게 돼 미세한 룩어헤드가 생긴다.
# ── VKOSPI (코스피200 변동성지수, 옵션 내재변동성) ──
#   실현변동성(20일)은 '이미 일어난 등락', VKOSPI는 '앞으로 30일 기대 등락'이다.
#   실측(2003~ 공통구간): 실현변동성이 VKOSPI를 4일 후행(최대상관 +0.914), 수준상관 0.890.
#   단독 IC는 VKOSPI가 우위(0.196 vs 0.181), 상위10% 진입 후 1년도 +22.2%/승률86% vs +21.4%/82%.
#   → VKOSPI를 주력으로 쓰고, 1995~2002 공백은 실현변동성이 메우도록 둘 다 남긴다
#     (표본외 실측: 현행만 0.7342 · VKOSPI만 0.7358 · 둘 다 0.7350 — 차이는 노이즈 수준이라
#      2003 이전 구간 보존과 화면 표시 정확성을 기준으로 '둘 다'를 택함).
try:
    _vkp = 'vkospi_daily.parquet'
    _vk = load(_vkp)['VKOSPI'].dropna()
    df['VKOSPI'] = _vk.resample('ME').last().reindex(df.index)
    # 최신 월은 월말 이전이라도 최근 거래일 값으로 덮어써 매일 갱신되게 한다(다른 지표와 동일 규칙)
    _vkl = _vk.index[-1].to_period('M').to_timestamp('M')
    if _vkl in df.index:
        df.loc[_vkl, 'VKOSPI'] = float(_vk.iloc[-1])
    HAS_VKOSPI = int(df['VKOSPI'].notna().sum()) >= 60
    COL_SRC['VKOSPI'] = 'KRX 한국거래소'
    if HAS_VKOSPI:
        FILE_INFO.append(('KRX 한국거래소', 'data.krx.co.kr MDC (collect_vkospi.py)', _vkp,
                          pd.Timestamp(os.path.getmtime(os.path.join(HERE, _vkp)),
                                       unit='s', tz='UTC').tz_convert('Asia/Seoul')
                            .strftime('%Y-%m-%d %H:%M')))
except Exception:
    HAS_VKOSPI = False

#   2007년 신용공여 제도 급성장으로 규모가 한 자릿수 배 뛰었다(2006 0.47조 → 2007 4.40조).
#   그 이전은 사실상 다른 시장이라 신호에서 잘라낸다. 차트에는 남기고 절단선만 긋는다.
CREDIT_FROM = pd.Timestamp('2007-01-01')
try:
    _kfp = 'kofia_daily.parquet'
    _kf = load(_kfp)
    _cr = (_kf['신용융자'] / _kf['투자자예탁금']).shift(1).resample('ME').last()
    df['신용융자/예탁금'] = _cr.reindex(df.index)
    # 원계열도 참고 지표로 싣는다(합성점수엔 안 들어감, 차트 비교용).
    #   레벨은 통화량과 함께 팽창하므로 차트에서 우상향 추세선을 경계로 쓴다(NOMINAL 목록).
    for _src, _lab in [('투자자예탁금', '고객예탁금(조원)'), ('신용융자', '신용융자(조원)'),
                       ('위탁매매미수금', '미수금(조원)')]:
        df[_lab] = (_kf[_src].shift(1) / 1e12).resample('ME').last().reindex(df.index)
        COL_SRC[_lab] = '금융투자협회 FreeSIS'
    df['반대매매비중(%)'] = _kf['반대매매비중'].shift(1).resample('ME').last().reindex(df.index)
    COL_SRC['반대매매비중(%)'] = '금융투자협회 FreeSIS'
    HAS_CREDIT = int(df['신용융자/예탁금'].notna().sum()) >= 60
    COL_SRC['신용융자/예탁금'] = '금융투자협회 FreeSIS'
    if HAS_CREDIT:
        FILE_INFO.append(('금융투자협회 FreeSIS', 'freesis.kofia.or.kr (collect_kofia.py)', _kfp,
                          pd.Timestamp(os.path.getmtime(os.path.join(HERE, _kfp)),
                                       unit='s', tz='UTC').tz_convert('Asia/Seoul')
                            .strftime('%Y-%m-%d %H:%M')))
except Exception:
    HAS_CREDIT = False

def ez(s, minp=36):
    return (s - s.expanding(minp).mean()) / s.expanding(minp).std()
def fwd(idx, h):
    P = df[f'{idx}_종가']; return np.log(P.shift(-h) / P)

FMT_X   = lambda v: f'{v:.2f}배'
FMT_DEV = lambda v: f'{v*100:+.0f}%'
FMT_PER = lambda v: f'{v:.1f}배'
FMT_PCT = lambda v: f'{v:.0f}%'
FMT_PP  = lambda v: f'{v:+.1f}%p'
FMT_SPR = lambda v: f'{v:.2f}%p'
FMT_WON = lambda v: f'{v:,.0f}원'
FMT_1   = lambda v: f'{v:.1f}'
FMT_2   = lambda v: f'{v:.2f}'
FMT_ROE = lambda v: f'{v:.1f}%'
FMT_YOY = lambda v: f'{v*100:+.0f}%'
FMT_RATE = lambda v: f'{v:.2f}%'

def signals_for(idx):
    per = df[f'{idx}_PER'].where(df[f'{idx}_PER'] > 0)
    # 일드갭: 이익수익률 − 국고채10년. 코스피는 예상PER 기준(예측력 2배), 코스닥은 후행PER.
    if idx == 'KOSPI' and HAS_FPE:
        _yg = 100 / df['예상PER'].where(df['예상PER'] > 0) - df['국고채10년']
        _yg_lab = '일드갭 (예상PER)'
    else:
        _yg = 100 / per - df['국고채10년']
        _yg_lab = '일드갭 (후행PER)'
    exp_yoy = np.log(df['수출금액']).diff(12)  # 수출 YoY
    _wti = df['WTI'] if 'WTI' in df else None
    _us10 = df['US10Y'].diff(12) if 'US10Y' in df else None
    _vixy = df['VIX'].pct_change(12) if 'VIX' in df else None
    _basey = df['기준금리'].diff(12)
    # ── 통화량(M1/M2) 파생 신호 ──
    #   ECOS에서 받아진 경우에만 만든다. 여러 후보를 넣고 IC 필터가 유효한 것만 남긴다.
    #   · M2 YoY: 유동성 증가율. 대표적 경기 선행지표(돈이 풀리면 자산가격 상방).
    #   · M2/M1 비율: 유동성 회전속도. 낮으면 돈이 안 돎(위험회피), 높으면 활발.
    #   · 시가총액/M2: 시장이 통화량 대비 얼마나 비싼가(버핏지표의 통화량 버전).
    _m2y = df['M2'].pct_change(12, fill_method=None) * 100 if 'M2' in df else None
    _m21 = (df['M2'] / df['M1']) if ('M2' in df and 'M1' in df) else None
    # 시총/M2: M2는 ECOS 특성상 2개월가량 지연 발표된다. 시가총액은 오늘 값인데
    #   최신 달 M2가 아직 없으면 비율이 NaN이 되어 차트 최신점이 끊긴다.
    #   가장 최근 발표된 M2를 앞으로 채워(ffill) 최신 시총과 나눈다.
    _mc_m2 = ((df[f'{idx}_시총'] / df['M2'].ffill())
              if ('M2' in df and f'{idx}_시총' in df) else None)
    # [주의] 경기선행종합지수에는 코스피가 구성항목으로 들어간다.
    #   실측: 선행지수 YoY와 코스피 YoY의 최대 상관이 +1개월(코스피가 앞섬) → 순환참조.
    #   한때 코스피 성분을 회귀로 제거한 잔차를 썼으나, 코스피가 역대급으로 움직이는
    #   구간(YoY +214%)에서 회귀계수 2.96이 6.3포인트를 빼버려 '과열(백분위 100%)'이
    #   '침체(4%)'로 뒤집히는 외삽 붕괴가 발생했다. 극단 구간에서 신호를 반전시키는
    #   보정은 쓸 수 없으므로 원본을 그대로 쓰고, 순환참조는 설명에 명시한다.
    # (표시명, 시리즈, 경제적prior부호(+1:높을수록강세 / -1:낮을수록강세), 값포맷, (고값어,저값어))
    sig = [
        ('PBR',          df[f'{idx}_PBR'],           -1, FMT_X,   ('고평가', '저평가')),
        ('PER',          per,                        -1, FMT_X,   ('고평가', '저평가')),
        (_yg_lab,        _yg,                        +1, FMT_PP,  ('확대', '축소')),
        ('실현변동성(20일)',       df[f'{idx}_변동성'],         +1, FMT_PCT, ('공포', '안정')),
        ('VIX 급등(YoY)', _vixy,                     +1, FMT_YOY, ('급등', '진정')),
        ('수출 YoY',      exp_yoy,                    +1, FMT_YOY, ('증가', '감소')),
        ('WTI 유가',      _wti,                       -1, FMT_RATE, ('고유가', '저유가')),
        ('환율(원/달러)',  df['원달러'],               +1, FMT_WON, ('원화약세', '원화강세')),
        ('경기선행지수',   df['선행지수'],             -1, FMT_1,   ('과열권', '침체권')),
        ('신용스프레드',   df['신용스프레드'],          +1, FMT_SPR, ('확대', '안정')),
        ('일드커브',      df['국고채10년']-df['국고채3년'], +1, FMT_PP, ('스팁', '플랫')),
        ('국고채10년',    df['국고채10년'],           -1, FMT_RATE, ('고금리', '저금리')),
        ('기준금리 YoY',  _basey,                     -1, FMT_PP,  ('인상', '인하')),
        ('기준금리',      df['기준금리'],             -1, FMT_RATE, ('고금리', '저금리')),
        ('M2 증가율(YoY)', _m2y,                      +1, FMT_YOY, ('유동성 확대', '긴축')),
        ('M2/M1 비율',    _m21,                       -1, FMT_2,   ('자금 위축', '자금 활발')),
        ('시가총액/M2',    _mc_m2,                     -1, FMT_2,   ('통화대비 고평가', '통화대비 저평가')),
    ]
    sig = [x for x in sig if x[1] is not None]
    if idx == 'KOSPI' and HAS_FPE:
        # 레벨 z-score는 이익 전망이 구조적으로 바뀌면 오염된다(최근 순이익 급증이 대표적).
        # 자기 추세(5년 이동평균) 대비 괴리로 보면 '지금 비싼가'를 훨씬 잘 잡는다.
        #   단독 IC 0.136 → 0.259 로 개선 확인.
        _fpe_dev = np.log(df['예상PER']) - np.log(df['예상PER']).rolling(60, min_periods=36).mean()
        sig.insert(2, ('예상PER 괴리', _fpe_dev, -1, FMT_DEV, ('추세대비 비쌈', '추세대비 쌈')))
        # ── Forward PBR (선행 PBR) ──
        #   현재 PBR은 '과거에 쌓인 순자산' 기준이라, 앞으로 벌 이익이 자본으로 쌓이는 걸
        #   반영 못 한다. 예상순이익이 크면 미래 순자산이 늘어 실질 밸류는 더 싸다.
        #     순자산(자본) = 시가총액 / 현재 PBR
        #     예상순이익 = 시가총액 / 예상PER   (예상PER = 시총/예상순이익 이므로)
        #     미래 순자산 = 순자산 + 예상순이익 × (1 − 배당성향)   (배당성향 0.35 가정)
        #     Forward PBR = 시가총액 / 미래 순자산
        _pbr = df[f'{idx}_PBR'].where(df[f'{idx}_PBR'] > 0)
        _fpe = df['예상PER'].where(df['예상PER'] > 0)
        _equity = 1.0 / _pbr                       # 시총=1로 정규화 → 자본 = 1/PBR
        _ni = 1.0 / _fpe                            # 예상순이익 = 1/예상PER
        _payout = 0.35                              # 배당성향(사내유보 65%가 자본에 쌓임)
        _fwd_equity = _equity + _ni * (1 - _payout)
        _fwd_pbr = 1.0 / _fwd_equity               # 시총(=1) / 미래자본
        sig.insert(3, ('선행 PBR', _fwd_pbr, -1, FMT_X, ('고평가', '저평가')))
    if idx == 'KOSPI' and HAS_VKOSPI:
        # ── 코스피 변동성 신호는 VKOSPI로 교체 (실현변동성은 참고 지표로 내림) ──
        #   코스피200 옵션 기반이라 KOSPI 전용. 코스닥은 자기 실현변동성을 계속 쓴다.
        #   방향은 +1 고정(급락 진행 중 IC 부호가 뒤집혀 바닥에서 '팔아라'가 되는 사고 방지).
        #   [왜 둘 다 쓰지 않는가] 두 지표는 상관 0.890으로 사실상 같은 말을 한다.
        #     둘 다 신호로 두면 극단증폭이 양쪽에 걸려 같은 공포를 두 번 센다.
        #     실측: 둘 다 넣으면 변동성 기여가 +0.734로 종합점수 +0.781의 94%를 차지했다.
        #     상관벌점은 증폭 '이전' 기본가중에만 걸려 이 중복을 못 막는다.
        #   [왜 VKOSPI가 이기는가] 같은 2003~ 구간에서 IC 0.196 vs 0.181,
        #     상위10% 진입 후 1년 +22.2%/승률86% vs +21.4%/82%,
        #     표본외 0.7358 vs 0.7342. 게다가 실현변동성은 VKOSPI를 4일 후행한다.
        sig = [t for t in sig if t[0] != '실현변동성(20일)']
        sig.insert(3, ('VKOSPI', df['VKOSPI'], +1, FMT_1, ('공포', '안정')))
    if idx == 'KOSPI' and HAS_CREDIT:
        # 레버리지가 높을수록 이후 12개월 수익이 나쁘다(prior −1, IC로 재확인됨).
        # ── 2007년 이전은 신호에서 제외 (구조 단절) ──
        #   2007년 신용공여 제도가 급성장하며 규모 자체가 한 자릿수 배로 뛰었다.
        #     2006년 신용융자 0.47조 · 비율 0.043  →  2007년 4.40조 · 비율 0.339 (9.4배)
        #   이 구간을 섞으면 expanding 평균이 0.237로 끌려 내려가, 최근 5년 기준
        #   1.7 백분위(사실상 최저)인 현재를 z=+0.28 '불리'로 표시하는 오류가 난다.
        #   (예상PER이 레벨 z 대신 추세 괴리를 쓰는 것과 같은 이유 — 구조 변화 오염)
        #   실측 비교(표본외 IC / 전환점 적중):
        #     전기간 0.708 (2008·2024 바닥 놓침) · 2005~ 0.699 · 2008~ 0.705
        #     EWM반감기5년 0.723 (2021 고점 놓침) · 2007~ 0.734 ★ 전환점 5/5 적중
        #   차트에는 전 기간을 그대로 두고 절단선만 표시한다(과거 맥락은 보이게).
        #   (6번째 원소를 쓰면 '주가성분 제거' 문구가 붙으므로 쓰지 않는다. 차트용 전체
        #    시리즈는 comp 딕셔너리가 따로 들고 있고, 백분위는 절단 후 기준이 맞다.)
        sig.append(('신용융자/예탁금', df['신용융자/예탁금'].where(df.index >= CREDIT_FROM),
                    -1, FMT_2, ('레버리지 과열', '청산 완료')))
    return sig

def _downside_sd(r, mu=None, ddof=1):
    """하방 반편차 - 평균 아래로 벗어난 값만으로 계산한 표준편차.
    켈리 분모로는 쓰지 않는다(아래 _kelly_empirical 주석 참조). 표시용."""
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) <= ddof:
        return 0.0
    m = float(r.mean()) if mu is None else float(mu)
    dn = r[r < m]
    if len(dn) == 0:
        return 0.0
    return float(np.sqrt(((dn - m) ** 2).sum() / (len(r) - ddof)))


def _kelly_empirical(r, rf=0.0, lo=-0.5, hi=1.5, n=201):
    """경험분포 켈리 - 과거 수익을 그대로 써서 E[log(1+f(r−rf))] 를 최대화.

    왜 σ² 공식을 안 쓰는가:
      f* = (μ−rf)/σ² 는 로그효용의 2차 근사라 정규분포를 사실상 전제한다.
      12개월 수익은 합산 효과로 정규에 가까워지지만 완전하지는 않다
      (중첩 기준 초과첨도 +1.9~3.0, |z|>3 이 정규의 7배).

    하방 반편차(σ_하방²)로 바꿔보는 것도 시도했으나 표본외에서 실패했다.
      분모가 제곱이라 레버리지가 4배로 뛰어, 코스피 무제한 켈리에서
      12개 코호트 중 10개가 파산하고 MDD −99% 가 나왔다.
      이론 방향은 맞아도 추정치가 불안정하면 쓸 수 없다.

    경험분포 방식은 분포 가정이 아예 없고, 파산 구간에서 log 가 −∞ 로
    발산하므로 과베팅을 스스로 막는다. 표본외에서 코스피·코스닥 모두
    파산 0, MDD 도 가장 낮았다. (수치는 check_tails.py / kelly_backtest)
    """
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 5:
        return 0.0
    best, bf = -np.inf, 0.0
    for f in np.linspace(lo, hi, n):
        w = 1.0 + f * (r - rf)
        if (w <= 1e-9).any():          # 파산 구간은 후보에서 제외
            continue
        v = float(np.mean(np.log(w)))
        if v > best:
            best, bf = v, f
    return bf


def regime(p):
    if p < .20: return '매우 불리', '#e5484d'
    if p < .40: return '불리', '#e08c3b'
    if p < .60: return '중립', '#d9a441'
    if p < .80: return '유리', '#5aa469'
    return '매우 유리', '#3fb37f'

EVENTS = [
    ('2007-06', '2008-06', '금융위기 직전 고점'),
    ('2008-07', '2009-12', '글로벌 금융위기 바닥'),
    ('2010-01', '2010-12', '금융위기 회복 국면'),
    ('2011-01', '2011-08', '차화정 랠리 고점'),
    ('2011-09', '2012-12', '유럽 재정위기'),
    ('2014-01', '2015-12', '박스권 장세'),
    ('2017-06', '2018-06', '반도체 슈퍼사이클 고점'),
    ('2018-07', '2019-12', '미중 무역분쟁'),
    ('2020-01', '2020-07', '코로나 폭락'),
    ('2020-08', '2022-01', '유동성 랠리 고점'),
    ('2022-02', '2022-12', '긴축 약세장'),
    ('2023-01', '2024-06', '금리 고점 구간'),
    ('2024-07', '2025-12', '저평가·밸류업 구간'),
    ('2026-01', '2026-12', '반도체 급등 후 조정'),
]
def _event(ts):
    p = ts.strftime('%Y-%m')
    for a, b, lab in EVENTS:
        if a <= p <= b: return lab
    return ''

def examples_for(sc, q, nq=5, top=2):
    """점수 q분위에 속했던 대표 시기(연속 구간)를 길이순으로 뽑아 이벤트명과 함께 반환"""
    try:
        b = pd.qcut(sc, nq, labels=False, duplicates='drop')
    except Exception:
        return []
    months = sc[b == q].index
    if len(months) == 0: return []
    groups, cur = [], [months[0]]
    for t in months[1:]:
        if (t.to_period('M') - cur[-1].to_period('M')).n <= 2: cur.append(t)
        else: groups.append(cur); cur = [t]
    groups.append(cur)
    groups = sorted(groups, key=len, reverse=True)[:top]
    groups = sorted(groups, key=lambda g: g[0])
    out = []
    for g in groups:
        span = (g[0].strftime('%Y.%m') if len(g) == 1
                else f"{g[0].strftime('%Y.%m')}~{g[-1].strftime('%y.%m')}")
        out.append((span, _event(g[len(g)//2])))
    return out

def _ridge_weights(bull, y, cols, lams=(10, 30, 100)):
    """다변량 Ridge 앙상블 가중치 — 겹치는 신호의 중복 기여를 제거."""
    D = pd.concat([bull[cols], y.rename('_y')], axis=1).dropna()
    if len(D) < 60:
        return None
    X = D[cols].values
    sd = X.std(0); sd[sd == 0] = 1
    Xs = (X - X.mean(0)) / sd
    yy = D['_y'].values - D['_y'].mean()
    G = Xs.T @ Xs; b = Xs.T @ yy
    W = []
    for lam in lams:
        try:
            beta = np.linalg.solve(G + lam * np.eye(len(cols)), b)
        except np.linalg.LinAlgError:
            continue
        a = np.abs(beta); s = a.sum()
        if s > 0: W.append(a / s)
    if not W:
        return None
    w = pd.Series(np.mean(W, axis=0), index=cols)
    return w / w.sum() if w.sum() else None

def _isotonic(vals, wts):
    """단조증가 제약 회귀 (Pool Adjacent Violators Algorithm).

    각 국면의 f*는 독립표본이 3개 안팎이라 추정오차가 매우 크다(승률 표준오차 ±28%p).
    그 탓에 '불리'가 '중립'보다 높게 나오는 순서 뒤집힘이 생긴다.
    합성점수가 높을수록 기대수익이 높다는 것은 모델의 핵심 전제(12개월 IC 0.6+)이므로,
    이 전제를 제약으로 걸어 뒤집힌 인접 구간을 표본가중 평균으로 병합한다.
    """
    y = [float(v) for v in vals]
    blocks = [[y[i], float(wts[i]), 1] for i in range(len(y))]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] <= blocks[i + 1][0] + 1e-12:
            i += 1; continue
        tw = blocks[i][1] + blocks[i + 1][1]
        blocks[i] = [(blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / tw,
                     tw, blocks[i][2] + blocks[i + 1][2]]
        blocks.pop(i + 1)
        if i > 0: i -= 1
    out = []
    for v, _w, cnt in blocks:
        out += [v] * cnt
    return out


def analyze(idx):
    sig = signals_for(idx)
    bull_cols, ic, direction, meta, _nobs = {}, {}, {}, {}, {}
    y12 = fwd(idx, 12)
    for n, s, base, fmt, states in [(t[0], t[1], t[2], t[3], t[4]) for t in sig]:
        xy = pd.concat([ez(s) * base, y12], axis=1, sort=True).dropna()
        # 유효 표본이 짧으면(예: 새로 추가됐거나 과거가 짧은 계열) IC를 신뢰할 수 없다.
        # 이런 신호는 분석(가중치)에서 빼되, 비교차트에는 그대로 남긴다.
        #   · 40개월 미만: IC 계산 불가 → 0
        #   · 60개월 미만: IC는 참고로 보여주되 가중치 후보에서 제외(아래 MIN_OBS)
        n_obs = len(xy)
        r = xy.iloc[:, 0].corr(xy.iloc[:, 1]) if n_obs > 40 else 0.0
        eff = base if r >= 0 else -base          # 실제 작동방향(IC 부호로 확정)
        # ── 변동성 지표는 방향 고정(항상 역발상 매수신호) ──
        #   "공포에 사라" — 변동성(실현변동성(20일)·VIX급등)이 극단으로 높을 때 이후 12개월 수익이
        #   좋다는 건 확립된 원리이고, 장기 IC도 양수다(코스닥 전체 +0.14, 2020~ +0.39,
        #   극단 상위15% 이후 +10~14%/승률 73%). 그런데 지금처럼 급락이 '진행 중'이면
        #   "변동성 최고점 직후 아직 더 하락" 구간이 표본에 들어가 단변량 IC가 일시적으로
        #   음수가 되고, 그러면 코드가 방향을 뒤집어 정작 바닥에서 '약세(팔아라)'로 표시하는
        #   치명적 오류가 생긴다(2026 코스닥에서 확인). 그래서 이 신호들은 IC 부호와
        #   무관하게 base(+1, 높을수록 강세)를 강제한다.
        if n in ('실현변동성(20일)', 'VKOSPI', 'VIX 급등(YoY)'):
            eff = abs(base)                      # 항상 강세방향 고정
        bull_cols[n] = ez(s) * eff
        ic[n] = abs(float(r))                    # 단변량 예측력(참고용)
        direction[n] = (eff, eff != base)        # (강세방향, 역발상여부)
        meta[n] = (s, fmt, states)
        _nobs[n] = n_obs
    # ── 경기선행지수 순환참조 보정 ──
    #   경기선행종합지수에는 코스피가 구성항목으로 들어가, 실측상 코스피가 +1개월 앞선다
    #   (동행/후행). 원본 IC(0.565) 중 코스피 성분을 회귀로 뺀 순수 경기정보 IC는 0.421로,
    #   약 26%가 순환참조로 부풀려진 것. 신호 값 자체는 원본을 쓰되(과거 직교화가 극단에서
    #   붕괴했기 때문), 가중치 산정에 쓰는 IC만 순수분으로 낮춰 다른 신호가 제 몫을 받게 한다.
    if idx == 'KOSPI' and '경기선행지수' in ic and '선행지수' in df:
        try:
            _liy = ez(df['선행지수']) * direction['경기선행지수'][0]
            _km = df['KOSPI_종가'].pct_change(12, fill_method=None)
            _c = pd.concat([_liy.rename('li'), _km.rename('k')], axis=1, sort=True).dropna()
            if len(_c) > 60:
                _rli, _rk = _c['li'].rank(pct=True), _c['k'].rank(pct=True)
                _resid = _rli - np.polyfit(_rk, _rli, 1)[0] * _rk
                _xy = pd.concat([_resid.rename('x'), y12.rename('y')], axis=1, sort=True).dropna()
                _pure = abs(float(_xy['x'].corr(_xy['y'])))
                ic['경기선행지수'] = min(ic['경기선행지수'], _pure)   # 순환참조분 제거
        except Exception:
            pass
    bull = pd.DataFrame(bull_cols).ffill(limit=3)

    # 예측력 없는 신호(억제변수) 제외: 단변량 |IC| < 0.10 이면 가중치 0.
    #   이렇게 하면 "국고채·PER이 코스피를 예측한다"는 해석 오류와 과최적화를 동시에 막는다.
    # 표본이 60개월 미만인 신호도 IC 신뢰도가 낮아 가중치 후보에서 제외한다
    #   (차트에는 남지만 분석엔 안 들어간다).
    IC_MIN, MIN_OBS = 0.10, 60
    # 참고지표(가중치 계산에서 제외, 차트에는 유지):
    #   시가총액/M2 — 단독 IC는 0.52로 높지만 PBR과 상관 0.84로 사실상 중복.
    #   실측: 이 신호를 빼도 표본외 IC 0.615→0.609 (기여 0.006). 게다가 M2가 2003년~로
    #   표본이 짧고, 최근 3년 +199% 급등해 z-score가 극단으로 치솟아 판정을 왜곡한다.
    #   → 통화량 대비 밸류는 차트로 관찰하되, 예측 가중은 PBR·예상PER에 맡긴다.
    REF_ONLY = {'시가총액/M2'}
    #   M2/M1 비율: 코스닥 IC 0.16으로 예측력이 약한데(PER IC 0.45의 1/3), 다른 신호와
    #   안 겹쳐 Ridge가 4%대 가중을 준다 — 예측력 대비 과하다(제거해도 표본외 0.581→0.569,
    #   손실 미미). 통화량 지표는 차트 참고용으로만 남기고 가중에서 뺀다.
    #   수출 YoY: 코스닥 IC −0.17로 경제상식(수출↑=강세)과 반대 방향이고 예측력도 약하다.
    #     제거 시 표본외가 오히려 개선(0.559→0.566). M2 증가율(IC 0.16, 약함)도 함께 빼면
    #     0.583까지 오른다. 방향 불안정·약예측력 신호가 다변량 가중을 왜곡하던 것.
    #   → 이 셋은 차트 참고용으로만 남기고 예측 가중에서 제외한다.
    REF_ONLY = REF_ONLY | {'M2/M1 비율', '수출 YoY', 'M2 증가율(YoY)'}
    cols = [c for c in bull.columns
            if ic[c] >= IC_MIN and _nobs.get(c, 0) >= MIN_OBS and c not in REF_ONLY]
    if len(cols) < 3:                                  # 너무 적으면 완화
        cols = sorted([c for c in bull.columns
                       if _nobs.get(c, 0) >= MIN_OBS and c not in REF_ONLY],
                      key=lambda c: -ic[c])[:5]
    w = _ridge_weights(bull, y12, cols)               # 다변량(중복 제거)
    if w is None:                                      # 실패 시 단변량 |IC| 폴백
        w = pd.Series({c: ic[c] for c in cols}); w = w / w.sum() if w.sum() else w
    else:
        # ── IC×Ridge 혼합 + 상관벌점 가중 ──
        #   순수 Ridge 계수만 쓰면 예측력 낮은 억제변수(일드커브 IC 0.10, 기준금리 등)가
        #   "다른 변수를 돕는 척" 가중을 부풀린다. 각 신호의 단독 예측력(IC)을 Ridge 계수에
        #   곱해 이를 눌렀다(실측 표본외 0.609→0.710).
        #   추가로, 서로 강하게 겹치는 신호 무리(예: 기준금리·기준금리YoY·일드커브가 상관
        #   0.5~0.6으로 얽힘)가 '집단으로' 가중을 빨아들이는 문제가 남아, 각 신호의 다른
        #   신호와의 평균절대상관으로 나눠주는 상관벌점을 더한다(강도 1.0). 겹칠수록 벌점이
        #   커져 독립적인 신호(실현변동성(20일)·일드갭 등)가 제 몫을 받는다.
        #   실측 표본외 IC: 혼합 0.708 → 상관벌점 추가 0.725 (추가 개선 확인).
        w = pd.Series({c: ic[c] * float(w[c]) for c in cols})
        try:
            _CC = bull[cols].corr().abs()
            _PEN = 1.0
            for c in cols:
                _ac = (_CC[c].sum() - 1) / (len(cols) - 1) if len(cols) > 1 else 0.0
                w[c] = w[c] / (1 + _PEN * _ac)
        except Exception:
            pass
        if w.sum(): w = w / w.sum()
    w = w.reindex(bull.columns).fillna(0.0)           # 제외된 신호는 0
    if w.sum(): w = w / w.sum()

    # ── 변동성 지표 극단 증폭 (역발상 강세신호) ──
    #   실측: 변동성(실현변동성(20일))이 높을수록 이후 12개월 수익이 좋다(상관 +0.19, 고변동 국면
    #   승률 73%). "공포에 사라" — VIX 급등은 바닥 신호다. 하지만 평상시 IC×Ridge로는
    #   실현변동성(20일) 가중이 낮아, 변동성이 z=+3~5로 폭발해도 종합점수에 거의 반영이 안 돼
    #   급락·고변동 국면을 '중립'으로 오판했다(2026 급락장에서 확인).
    #   → 변동성 z가 극단(|z|>2)일 때만 그 초과분에 비례해 가중을 증폭한다(k=1.0).
    #     단 기본 가중이 너무 낮으면(코스닥 실현변동성(20일) 2%) 증폭 배율을 곱해도 절대값이
    #     작아 효과가 미미하므로, 극단일 때는 하한(3%)을 먼저 적용한 뒤 증폭한다.
    #     평상시(|z|<2)엔 증폭 0이라 기본 가중 유지 → 표본외 성능 보존.
    #     지금처럼 z=+3.6~5.2로 폭발하면 가중이 크게 커져 확실히 '유리'로 잡는다.
    #   실측 표본외 IC: k=0 0.79 → k=1.0 0.74 (약간 희생, 극단국면 포착과 맞바꿈).
    _VOL_AMP = {'실현변동성(20일)': 1.0, 'VKOSPI': 1.0, 'VIX 급등(YoY)': 1.0}
    _VOL_FLOOR = 0.03
    _cur_row = bull.loc[bull.dropna(how='all').index[-1]]
    _amped = False
    for _vn, _k in _VOL_AMP.items():
        if _vn in w.index and ic.get(_vn, 0) >= 0.10:
            _z = abs(float(_cur_row.get(_vn))) if pd.notna(_cur_row.get(_vn)) else 0.0
            _amp = 1.0 + _k * max(0.0, _z - 2.0)
            if _amp > 1.0:
                base = max(w[_vn], _VOL_FLOOR)     # 극단일 땐 하한 먼저
                w[_vn] = base * _amp; _amped = True
    if _amped and w.sum():
        w = w / w.sum()

    def wsum(row):
        v = row.dropna().index
        return (row[v] * (w[v] / w[v].sum())).sum() if len(v) and w[v].sum() else np.nan
    score = bull.apply(wsum, axis=1)
    sc = score.dropna()
    cur, pct, asof = float(sc.iloc[-1]), float((sc < sc.iloc[-1]).mean()), sc.index[-1]
    cur_bull = bull.loc[bull.dropna(how='all').index[-1]]

    reads = []
    for _t in sig:
        n, s, base, fmt, states = _t[0], _t[1], _t[2], _t[3], _t[4]
        # 6번째 원소가 있으면 '화면 표시용 원본 시리즈'다.
        # (예: 경기선행지수는 순환참조 제거를 위해 잔차로 계산하지만,
        #      화면에는 실제 발표치를 보여야 한다.)
        disp = _t[5] if len(_t) > 5 and _t[5] is not None else s
        # 값은 '실제 발표치'를 보여주고, 백분위·강도는 '실제 신호'로 계산한다.
        _dr = disp.dropna(); rv = float(_dr.iloc[-1])
        raw = s.dropna(); pb = float((raw < float(raw.iloc[-1])).mean()) * 100
        eff, contra = direction[n]
        desc = ('낮을수록' if eff < 0 else '높을수록') + ' 강세' + (' · 역발상' if contra else '')
        if len(_t) > 5 and _t[5] is not None:
            desc += ' · 주가성분 제거 후 사용'
        z = cur_bull.get(n)
        reads.append((n, desc, fmt, rv, pb, (float(z) if pd.notna(z) else None),
                      float(w[n]), states))
    reads.sort(key=lambda r: -r[6])   # 가중치 큰 순
    # 점수 5분위 → 미래수익
    # ── 점수구간별 기대수익 사다리 ──
    #   [버그 수정] qcut(duplicates='drop')은 점수 중복이 많으면 구간이 5개 미만으로
    #   줄어, 라벨과 실제 구간이 어긋나 역전이 생겼다. rank 기반으로 항상 NB구간을
    #   보장하고, 표본이 적은 구간의 평균·승률이 튀어 순서가 뒤집히는 것은
    #   등위회귀(isotonic, 표본수 가중)로 '평균과 승률 모두' 단조 증가를 강제한다.
    NB = 7                                         # 점수구간 개수 (7단계)
    def _bins(s):
        return np.clip((s.rank(pct=True) * NB).astype(int).clip(0, NB-1), 0, NB-1)
    def _mono(vals, ns):
        # 표본수 가중 등위회귀(PAVA)로 단조 증가 강제
        v = list(vals); w = [max(n, 1) for n in ns]; i = 0
        while i < len(v) - 1:
            if v[i] > v[i+1]:
                nv = (v[i]*w[i] + v[i+1]*w[i+1]) / (w[i]+w[i+1])
                v[i] = v[i+1] = nv; w[i] = w[i+1] = w[i]+w[i+1]
                if i > 0: i -= 1
            else:
                i += 1
        return v
    tbl = {}
    # ── 장기 드리프트(CAGR) 보정 + 부드러운 십분위 ── [재설계 v4]
    #   국면별 기대수익을 실현치로만 계산하면 표본기간 편향으로 '중립'이 비관적으로 나온다.
    #   [v1~v3 히스토리] 표본평균빼기(음수보정)·중립앵커(극단뭉갬)를 거쳐, v3는
    #   'CAGR + (구간raw − 구간평균)'으로 전체평균을 CAGR에 맞추고 상대편차를 보존한다.
    #   [v4 추가] 표본이 220여개뿐이라 딱딱하게 10등분하면 구간당 22개로 노이즈가 커서
    #   raw가 뒤죽박죽(비단조)이 되고, 그걸 PAVA로 뭉개면 중립이 -0%로 눌린다(민용 지적).
    #   → 각 십분위를 '중심 ±20% 표본이 겹치는 이동창(rolling)'으로 계산해 부드럽게 만든다.
    #   IC는 0.5로 강하니, 겹침 평균만으로도 자연스러운 단조가 나와 PAVA 왜곡이 사라진다.
    #   주의: "미래에도 과거만큼 오른다"는 가정. 저성장 진입 시 과대추정 위험.
    #   CAGR: 우리 시계열은 1995년(코스피 926)부터라 이전 고성장기(1980~94)가 빠져 6.5%로
    #   낮게 나온다. 코스피 공식 기준점은 1980.1.4=100이므로, 이를 시작점으로 삼아 진짜
    #   장기 CAGR(약 9.5%)을 쓴다. 현재가/100 을 1980년부터의 연수로 환산.
    _Plong = df[f'{idx}_종가'].dropna()
    if idx == 'KOSPI':
        _base_val, _base_dt = 100.0, pd.Timestamp('1980-01-04')
    else:  # 코스닥 기준점 1996.7.1 = 1000
        _base_val, _base_dt = 1000.0, pd.Timestamp('1996-07-01')
    _yrs = max((_Plong.index[-1] - _base_dt).days / 365.25, 1)
    _cagr_log = float(np.log(_Plong.iloc[-1] / _base_val) / _yrs)   # 연 로그수익(장기)

    def _smooth_bins(xs, ys, nb):
        # 점수 오름차순 정렬 후, 각 십분위 중심 ±20% 표본이 겹치는 이동창 평균/승률
        o = np.argsort(xs); ys2 = np.asarray(ys)[o]
        n = len(ys2); win = max(int(n * 0.20), 8)
        mval, wval, nval = [], [], []
        for b in range(nb):
            c = int((b + 0.5) / nb * n)
            lo = max(0, c - win // 2); hi = min(n, c + win // 2)
            seg = ys2[lo:hi]
            mval.append(float(np.mean(seg)))
            wval.append(float((seg > 0).mean()))
            nval.append(len(seg))
        return mval, wval, nval

    for h in (3, 6, 12):
        xy = pd.concat([score.rename('s'), fwd(idx, h).rename('y')], axis=1, sort=True).dropna()
        raw_means, wins_raw, ns = _smooth_bins(xy['s'].values, xy['y'].values, NB)
        _bar = sum(raw_means) / NB                     # 구간평균들의 평균
        _target = _cagr_log * (h / 12.0)               # 기간환산 장기 CAGR
        # 각 구간: 전체평균을 CAGR로 옮기되 상대편차 보존, PAVA는 안전장치로만
        means = _mono([_target + (rm - _bar) for rm in raw_means], ns)
        wins = _mono(wins_raw, ns)
        tbl[h] = list(zip(means, wins))
    edges = pd.qcut(sc, NB, labels=False, duplicates='drop', retbins=True)[1]
    cbin = int(np.clip(np.digitize(cur, edges[1:-1]), 0, NB-1))
    xy12 = pd.concat([score.rename('s'), fwd(idx, 12).rename('y')], axis=1, sort=True).dropna()
    xy12['b'] = _bins(xy12['s'])
    tbl['n12'] = int((xy12['b'] == cbin).sum())
    tbl['NB'] = NB

    # ── 지수 예측 범위: D방식 (현재가 × 장기추세 + 국면프리미엄 절반) ──
    #   [문제] 과거 "최유리 국면"은 대부분 폭락 직후 바닥(IMF·금융위기·코로나)이라, 그때의
    #   12개월 수익이 +40~200%다. 이걸 그대로 현재가에 적용하면, 지금처럼 지수가 이미
    #   고점(6,595)인데도 +49%(9,900)로 과대추정된다 — 출발점이 바닥이 아닌데 바닥 반등률을
    #   붙이는 오류.
    #   [D방식] 예측 중심 = 현재가 × exp(CAGR + 국면프리미엄×0.5).
    #     · 베이스는 장기추세(CAGR): 현재가에서 출발하므로 고점/저점 출발을 그대로 존중.
    #     · 국면프리미엄 = (그 국면 과거수익 − 전체평균), 축소계수 0.5로 절반만 반영.
    #       → 유리하면 CAGR 위로, 불리하면 CAGR 아래로. 단 과거 극단 반등률을 절반만 실어
    #         비현실적 폭등 예측을 억제한다.
    #     · 밴드폭은 그 국면의 로버스트 변동성(MAD×1.4826)으로 ±1.04σ(약 70% 구간).
    _px = float(df[f'{idx}_종가'].dropna().iloc[-1])
    _SHRINK = 0.5
    _bar12 = sum(raw_means) / NB          # 12개월 구간평균들의 평균(위 루프의 마지막 h=12 값)
    # 예측용 정렬표본(점수 오름차순) + 창 크기
    xy12s = xy12.sort_values('s').reset_index(drop=True)
    _win12 = max(int(len(xy12s) * 0.20), 8)

    def _proj_for(_b):
        cc = int((_b + 0.5) / NB * len(xy12s)); l = max(0, cc - _win12 // 2); h_ = min(len(xy12s), cc + _win12 // 2)
        seg = xy12s['y'].iloc[l:h_]
        if len(seg) < 5:
            return None
        _prem = (float(seg.mean()) - _bar12) * _SHRINK
        _center = _cagr_log + _prem       # 로그: 장기추세 + 국면프리미엄(절반)
        _med = seg.median()
        _rsd = float((seg - _med).abs().median() * 1.4826)   # 로버스트 표준편차
        # 여러 신뢰구간을 미리 계산(사용자가 30/50/70/90% 선택). z: 정규분포 양측 분위.
        _Z = {30: 0.385, 50: 0.674, 70: 1.036, 90: 1.645}
        _bands = {p: [float(_px * np.exp(_center - z * _rsd)),
                      float(_px * np.exp(_center + z * _rsd))] for p, z in _Z.items()}
        return dict(lo=float(_px * np.exp(_center - 1.036 * _rsd)),
                    hi=float(_px * np.exp(_center + 1.036 * _rsd)),
                    med=float(_px * np.exp(_center)),
                    up=float((seg > 0).mean()),
                    center=_center, rsd=_rsd, bands=_bands)

    _pc = _proj_for(cbin)
    if _pc is not None:
        _c, _rsd = _pc['center'], _pc['rsd']
        proj = dict(px=_px, up=_pc['up'],
                    p=[float(_px * np.exp(_c + z * _rsd)) for z in (-1.28, -0.52, 0.0, 0.52, 1.28)],
                    lo=_pc['lo'], hi=_pc['hi'], med=_pc['med'], bands=_pc['bands'],
                    samples=[float(_px * np.exp(v)) for v in
                             (xy12['y'] * _SHRINK + (_cagr_log - _bar12 * _SHRINK)).values])
    else:
        proj = None
    # 각 구간(bin)의 예측 범위 — 체크박스로 국면이 바뀌면 예측 박스도 갱신
    projbins = {}
    for _b in range(NB):
        _pb = _proj_for(_b)
        if _pb is not None:
            projbins[_b] = dict(lo=_pb['lo'], hi=_pb['hi'], med=_pb['med'], up=_pb['up'],
                                bands=_pb['bands'])
    tbl['projbins'] = projbins
    tbl['px_now'] = _px

    # ── 베팅비율: 전통적 켈리 공식  f* = p − q/b ──────────────────
    #   p = 이길 확률(향후 12개월 수익 > 0),  q = 1−p
    #   b = 손익비 = 이겼을 때 평균수익 / 졌을 때 평균손실
    #   상한 +150%, 하한 −50%.
    #   [주의] 구간 경계는 '미래수익이 존재하는 과거 구간'에서 뽑되,
    #          현재 구간은 반드시 '현재 점수'를 그 경계에 대입해 구한다.
    #          (과거 데이터의 마지막 행은 12개월 전 시점이라 그대로 쓰면 어긋남)
    P12 = df[f'{idx}_종가']
    r12b = P12.pct_change(12).shift(-12)
    # 연속형 켈리에 쓸 무위험수익률(국고채3년, 연율 → 소수). 없으면 0.
    _rf = (df['국고채3년'] / 100.0) if '국고채3년' in df else pd.Series(0.0, index=df.index)
    _S = pd.concat([sc.rename('s'), r12b.rename('r'), _rf.rename('rf')],
                   axis=1, sort=True).dropna()
    KMAX, KMIN = 1.5, -0.5
    betrows, bet_now, cur_kb = [], 0.0, 2
    if len(_S) >= 40:
        edges = np.quantile(_S['s'], [.2, .4, .6, .8])
        _S['kb'] = np.digitize(_S['s'], edges)
        cur_kb = int(np.digitize([cur], edges)[0])       # ← 현재 점수로 판정
        names = ['매우 불리', '불리', '중립', '유리', '매우 유리']
        for b_ in range(5):
            _gsub = _S[_S['kb'] == b_]
            g = _gsub['r']
            rf_bucket = _gsub['rf'].mean() if len(_gsub) else 0.0
            if not len(g):
                betrows.append(dict(nm=names[b_], p=float('nan'), q=float('nan'),
                                    aw=float('nan'), al=float('nan'), b=float('nan'),
                                    f=0.0, fc=0.0, n=0)); continue
            win, los = g[g > 0], g[g <= 0]
            p_ = len(win) / len(g); q_ = 1 - p_
            aw = float(win.mean()) if len(win) else 0.0
            al = float(abs(los.mean())) if len(los) else 0.0
            if al > 0 and aw > 0:
                b_ratio = aw / al; f_ = p_ - q_ / b_ratio
            elif al == 0:                      # 진 적이 없음 → 최대 베팅
                b_ratio = float('inf'); f_ = KMAX
            else:                              # 이긴 적이 없음 → 최소 베팅
                b_ratio = 0.0; f_ = KMIN
            fc = max(KMIN, min(KMAX, f_))
            # ── (2) 연속형 켈리: 경험분포로 기대로그성장 최대화 ──
            #   수익률을 이산 승/패가 아니라 연속 분포로 보고 최적 비중을 찾는다.
            #   단순 켈리가 '이겼나 졌나'만 보는 반면 이쪽은 분포 전체를 쓴다.
            #   σ² 공식이 아니라 경험분포를 쓰는 이유는 _kelly_empirical 주석 참조.
            mu = float(g.mean()); sd = float(g.std(ddof=1)) if len(g) > 1 else 0.0
            sd_dn = _downside_sd(g.values, mu)
            rf_ = float(rf_bucket) if rf_bucket == rf_bucket else 0.0
            f_c = _kelly_empirical(g.values, rf_, KMIN, KMAX)
            fcc = max(KMIN, min(KMAX, f_c))
            betrows.append(dict(nm=names[b_], p=p_, q=q_, aw=aw, al=al, b=b_ratio,
                                f=f_, fc=fc, n=int(len(g)),
                                mu=mu, sd=sd, sd_dn=sd_dn, var=sd_dn ** 2,
                                rf=rf_, fcont=f_c, fcontc=fcc))
        # 순서 뒤집힘 보정: 점수가 높을수록 f*가 커지도록 단조 제약
        _valid = [r for r in betrows if r['n'] > 0]
        if len(_valid) >= 2:
            _sm = _isotonic([r['f'] for r in _valid], [r['n'] for r in _valid])
            for r, v in zip(_valid, _sm):
                r['f_adj'] = v
                r['fc'] = max(KMIN, min(KMAX, v))
            _sc2 = _isotonic([r['fcont'] for r in _valid], [r['n'] for r in _valid])
            for r, v in zip(_valid, _sc2):
                r['fcont_adj'] = v
                r['fcontc'] = max(KMIN, min(KMAX, v))
        for r in betrows:
            r.setdefault('f_adj', r['f'])
            r.setdefault('fcont_adj', r.get('fcont', 0.0))
        bet_now = betrows[cur_kb]['fc'] if betrows else 0.0
    bet = dict(now=bet_now, pct=pct, cur_kb=cur_kb, rows=betrows,
               kmax=KMAX, kmin=KMIN)

    return dict(sc=sc, cur=cur, pct=pct, asof=asof, reads=reads, tbl=tbl, cbin=cbin, bet=bet,
                proj=proj, idx=idx, qedges=list(edges[1:-1]),
                ic=ic, w={n: float(w[n]) for n in w.index}, direction=direction,
                px=float(df[f'{idx}_종가'].dropna().iloc[-1]))

def dist_strip(sc, cur, color):
    W, base, padL, padR = 900, 92, 44, 44
    lo, hi = sc.min(), sc.max()
    X = lambda v: padL + (v - lo) / (hi - lo) * (W - padL - padR)
    cnt, edges = np.histogram(sc, bins=32, range=(lo, hi)); cmax = cnt.max()
    bars = ''.join(f'<rect x="{X(edges[i]):.1f}" y="{base-(c/cmax)*58:.1f}" '
                   f'width="{max(X(edges[i+1])-X(edges[i])-1,1):.1f}" height="{(c/cmax)*58:.1f}" '
                   f'fill="#2b3648" rx="1"/>' for i, c in enumerate(cnt))
    ticks = ''.join(f'<line x1="{X(t):.1f}" y1="{base}" x2="{X(t):.1f}" y2="{base+5}" stroke="#3a465a"/>'
                    f'<text x="{X(t):.1f}" y="{base+18}" fill="#6b7a90" font-size="11" text-anchor="middle" '
                    f'font-family="ui-monospace,monospace">{t:+.1f}</text>' for t in [lo, (lo+hi)/2, hi])
    nx = X(cur)
    return (f'<svg viewBox="0 0 {W} 118" width="100%" preserveAspectRatio="xMidYMid meet">'
            f'<defs><linearGradient id="rg{color[1:]}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="#e5484d"/><stop offset="0.5" stop-color="#d9a441"/>'
            f'<stop offset="1" stop-color="#3fb37f"/></linearGradient></defs>'
            f'<rect x="{padL}" y="{base+2}" width="{W-padL-padR}" height="4" fill="url(#rg{color[1:]})" rx="2" opacity="0.85"/>'
            f'{bars}{ticks}'
            f'<line x1="{nx:.1f}" y1="16" x2="{nx:.1f}" y2="{base}" stroke="{color}" stroke-width="2.5"/>'
            f'<circle cx="{nx:.1f}" cy="16" r="5" fill="{color}"/>'
            f'<text x="{nx:.1f}" y="9" fill="{color}" font-size="12" text-anchor="middle" '
            f'font-family="ui-monospace,monospace" font-weight="600">지금</text></svg>')

def render_signals(reads, idx_key=''):
    zmax = max((abs(r[5]) for r in reads if r[5] is not None), default=1.5)
    out = '<div class="siglist">'
    for i, (n, desc, fmt, rv, pb, z, wt, states) in enumerate(reads, 1):
        if 100 - pb < 1: loc = '최고'
        elif pb < 1:     loc = '최저'
        elif pb >= 50:   loc = f'상{100-pb:.0f}%'
        else:            loc = f'하{pb:.0f}%'
        z_attr = '' if z is None else f'{z:.4f}'
        is_ref = wt <= 0 and z is not None       # 참고지표(가중 0)
        if is_ref:
            # 참고지표는 점수에 영향이 없으므로 체크박스를 비활성화(회색)한다
            cb = (f'<input type="checkbox" class="sigck" checked disabled '
                  f'data-idx="{idx_key}" data-w="0" data-z="{z_attr}" title="참고지표 · 종합점수 미반영">')
        else:
            cb = (f'<input type="checkbox" class="sigck" checked '
                  f'data-idx="{idx_key}" data-w="{wt:.6f}" data-z="{z_attr}" '
                  f'onchange="recalc(\'{idx_key}\')">')
        w_disp = '참고' if is_ref else f'{wt*100:.0f}%'
        if z is None:
            out += (f'<div class="sg"><label class="sg-ck">{cb}</label>'
                    f'<span class="sg-i">{i}</span><span class="sg-n">{n}</span>'
                    f'<span class="sg-bar"><span class="sg-mid"></span></span>'
                    f'<span class="sg-val na">대기</span>'
                    f'<span class="sg-w">{wt*100:.0f}%</span></div>')
            continue
        pos = z >= 0; col = '#3fb37f' if pos else '#e5484d'
        width = min(abs(z)/zmax, 1)*50; side = 'left:50%' if pos else 'right:50%'
        arrow = '▲' if pos else '▼'
        # 한 줄: 체크·번호·이름 | 미니바 | z값·현재값·백분위 | 가중
        out += (f'<div class="sg" title="{fmt(rv)} · 역대 {loc} · {desc}">'
                f'<label class="sg-ck">{cb}</label>'
                f'<span class="sg-i">{i}</span><span class="sg-n">{n}</span>'
                f'<span class="sg-bar"><span class="sg-mid"></span>'
                f'<span class="sg-fill" style="{side};width:{width:.1f}%;background:{col}"></span></span>'
                f'<span class="sg-val" style="color:{col}">{arrow}{abs(z):.1f}\u03c3</span>'
                f'<span class="sg-rv">{fmt(rv)}</span>'
                f'<span class="sg-w">{w_disp}</span></div>')
    return out + '</div>'

def render_forward(tbl, cbin, sc=None, ik=''):
    NB = tbl.get('NB', 10)
    m12, w12 = tbl[12][cbin]; col = '#3fb37f' if m12 >= 0 else '#e5484d'
    mh = ''
    for h in (3, 6, 12):
        m, wn = tbl[h][cbin]; c = '#3fb37f' if m >= 0 else '#e5484d'
        mh += (f'<div class="mh"><span class="mh-h">{h}개월</span>'
               f'<span class="mh-m" id="mhm-{ik}-{h}" style="color:{c}">{m:+.0%}</span>'
               f'<span class="mh-w" id="mhw-{ik}-{h}">승률 {wn:.0%}</span></div>')
    # 라벨: 점수(국면) 백분위 + 유불리 표시.
    #   b가 높을수록 종합점수 상위(유리), 낮을수록 하위(불리). NB단계 대칭 배분.
    def _lab(b):
        lo = b * 100 // NB
        hi = (b + 1) * 100 // NB
        # 가운데를 중립, 위/아래로 유리/불리 대칭 배분 (7단계: 불리3·중립1·유리3 → 상하 대칭)
        _mid = (NB - 1) / 2.0
        if b >= _mid + 0.5:
            tag = '유리'
        elif b <= _mid - 0.5:
            tag = '불리'
        else:
            tag = '중립'
        return f'점수 {lo}~{hi}% · {tag}'
    lad = ''
    for b in range(NB - 1, -1, -1):
        mean, win = tbl[12][b]; c = '#3fb37f' if mean >= 0 else '#e5484d'
        here = ' here' if b == cbin else ''
        lab = _lab(b)
        tag = '<span class="lad-tag">지금 여기</span>' if b == cbin else ''
        ex = ''
        if sc is not None and b in (0, NB - 1):
            eg = examples_for(sc, b, nq=NB)
            if eg:
                ex = ('<div class="lad-ex">' + ' · '.join(
                    f'<b>{sp}</b> {lb}' if lb else f'<b>{sp}</b>' for sp, lb in eg) + '</div>')
        lad += (f'<div class="lad{here}" id="lad-{ik}-{b}"><div class="lad-r"><span class="lad-b">{lab}</span>'
                f'<span class="lad-m" style="color:{c}">{mean:+.0%}</span>'
                f'<span class="lad-w">승률 {win:.0%}</span>'
                f'<span class="lad-tagwrap" id="ladtag-{ik}-{b}">{tag}</span></div>{ex}</div>')
    return (f'<div class="headline"><div class="big" id="fbig-{ik}" style="color:{col}">{m12:+.0%}</div>'
            f'<div class="cap">향후 12개월 평균 · <span id="fcap-{ik}">상승확률 {w12:.0%}</span></div></div>'
            f'<div class="mh-row">{mh}</div>'
            f'<h2>점수 구간별 12개월 수익 ({NB}단계 · 지금 위치 강조)</h2>{lad}')

def proj_svg(a, color):
    pj = a['proj']
    if not pj: return ''
    ik = a['idx']
    W, H = 460, 96
    xs = sorted(pj['samples'])
    # 축 범위: 체크박스로 국면이 바뀌면 다른 bin의 밴드도 보여야 하므로,
    #   모든 구간의 90% 밴드 상·하한까지 포함하도록 넓힌다.
    _allx = list(xs)
    for _bv in a['tbl'].get('projbins', {}).values():
        _b90 = _bv['bands'].get(90)
        if _b90: _allx += [_b90[0], _b90[1]]
    lo_ax, hi_ax = min(_allx) * 0.98, max(_allx) * 1.02
    X = lambda v: 8 + (v - lo_ax) / (hi_ax - lo_ax) * (W - 16)
    # 히스토그램(고정 배경)
    n = 26
    cnt, edges = np.histogram(xs, bins=n, range=(lo_ax, hi_ax))
    cmax = max(cnt) or 1
    bars = ''.join(
        f'<rect x="{X(edges[i]):.1f}" y="{60-(c/cmax)*46:.1f}" width="{(W-16)/n-1:.1f}" '
        f'height="{(c/cmax)*46:.1f}" fill="#2b3648" rx="1"/>' for i, c in enumerate(cnt))
    _b50 = pj['bands'][50]
    # band/med/labels 는 id를 부여해 JS가 국면·구간% 바뀔 때 다시 그린다.
    band = (f'<rect id="pjband-{ik}" x="{X(_b50[0]):.1f}" y="12" width="{X(_b50[1])-X(_b50[0]):.1f}" height="48" '
            f'fill="{color}" opacity="0.12" rx="3"/>')
    pxline = f'<line x1="{X(pj["px"]):.1f}" y1="10" x2="{X(pj["px"]):.1f}" y2="62" stroke="#e6edf3" stroke-width="2"/>'
    medline = f'<line id="pjmedln-{ik}" x1="{X(pj["med"]):.1f}" y1="10" x2="{X(pj["med"]):.1f}" y2="62" stroke="{color}" stroke-width="2"/>'
    labs = (f'<text id="pjlo-{ik}" x="{X(_b50[0]):.1f}" y="76" fill="#8b98ab" font-size="10" text-anchor="middle" '
            f'font-family="ui-monospace">{_b50[0]:,.0f}</text>'
            f'<text id="pjhi-{ik}" x="{X(_b50[1]):.1f}" y="76" fill="#8b98ab" font-size="10" text-anchor="middle" '
            f'font-family="ui-monospace">{_b50[1]:,.0f}</text>'
            f'<text x="{X(pj["px"]):.1f}" y="90" fill="#e6edf3" font-size="10" text-anchor="middle" '
            f'font-family="ui-monospace">현재 {pj["px"]:,.0f}</text>'
            f'<text id="pjmedlab-{ik}" x="{X(pj["med"]):.1f}" y="8" fill="{color}" font-size="10" text-anchor="middle" '
            f'font-family="ui-monospace">중앙 {pj["med"]:,.0f}</text>')
    # 축 범위·현재가·색을 JS에 넘겨 좌표 변환에 사용
    axis = (f'<script>window.PJAX=window.PJAX||{{}};window.PJAX["{ik}"]='
            f'{{lo:{lo_ax:.2f},hi:{hi_ax:.2f},W:{W},px:{pj["px"]:.2f},color:"{color}"}};</script>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet">'
            f'{band}{bars}{pxline}{medline}{labs}</svg>{axis}')

def section(label, a):
    rl, rc = regime(a['pct'])
    m12, w12 = a['tbl'][12][a['cbin']]
    mcol = '#3fb37f' if m12 >= 0 else '#e5484d'
    pj = a['proj']
    proj_html = ''
    if pj:
        _b50 = pj['bands'][50]
        proj_html = (f'<div class="projbox"><div class="proj-h">'
                     f'<span>12개월 뒤 지수 예측 <b id="pjrange-{a["idx"]}" style="color:{rc}">'
                     f'{_b50[0]:,.0f} ~ {_b50[1]:,.0f}</b> '
                     f'<select class="proj-sel" id="pjsel-{a["idx"]}" onchange="setBand(\'{a["idx"]}\')">'
                     f'<option value="30">30% 구간</option>'
                     f'<option value="50" selected>50% 구간</option>'
                     f'<option value="70">70% 구간</option>'
                     f'<option value="90">90% 구간</option></select></span>'
                     f'<span class="proj-med" id="pjmed-{a["idx"]}">중앙 {pj["med"]:,.0f} · 상승확률 {pj["up"]:.0%}</span></div>'
                     f'{proj_svg(a, rc)}'
                     f'<div class="proj-cap">현재 종합점수 <span id="pjscore-{a["idx"]}">{a["cur"]:+.2f}({rl})</span>가 놓인 국면 기준, '
                     f'<b>현재가 {pj["px"]:,.0f}에서 장기추세(코스피 기준점 1980=100 이후 CAGR 약 9.5%)</b>만큼 오르는 것을 '
                     f'중심으로, 국면 프리미엄을 절반(50%)만 얹어 추정한 범위입니다. '
                     f'과거 "유리 국면"은 대개 폭락 직후 바닥이라 그때 반등률(+40~200%)을 지금 고점에 '
                     f'그대로 적용하면 과대추정되므로, 국면 효과를 절반만 반영해 억제했습니다. '
                     f'구간(%)은 그 국면 과거 변동성 기준 신뢰구간입니다. '
                     f'예측이 아니라 과거 통계 기반 참고치이며, "미래에도 과거만큼 오른다"는 가정이 깔려 있어 '
                     f'저성장 진입 시 과대추정될 수 있습니다.</div></div>')
    ik = a['idx']
    # 종합점수 분포(과거 전체)를 JS에 넘겨 체크박스로 재계산 시 백분위를 다시 구한다
    _scdist = json.dumps([round(float(v), 4) for v in a['sc'].dropna().tolist()])
    _edges = json.dumps([round(float(x), 4) for x in a['qedges']])
    _NB = a['tbl'].get('NB', 10)
    _bins = json.dumps({str(b): [round(a['tbl'][12][b][0], 4), round(a['tbl'][12][b][1], 4)]
                        for b in range(_NB)})
    _binmh = json.dumps({str(b): {str(h): [round(a['tbl'][h][b][0], 4), round(a['tbl'][h][b][1], 4)]
                                  for h in (3, 6, 12)} for b in range(_NB)})
    # 각 구간의 예측 범위(체크박스로 국면 바뀌면 예측박스 갱신) + 신뢰구간별 밴드
    _pjb = json.dumps({str(b): {'med': round(v['med']), 'up': round(v['up'], 3),
                                'bands': {str(p): [round(x[0]), round(x[1])] for p, x in v['bands'].items()}}
                       for b, v in a['tbl'].get('projbins', {}).items()})
    return (f'<div class="sec" data-idx="{ik}"><div class="sec-head">'
            f'<div class="sec-t">{label} <span class="sec-px">{a["px"]:,.1f}</span></div>'
            f'<div class="sec-score"><span class="ss" id="ss-{ik}" style="color:{rc}">{a["cur"]:+.2f}</span>'
            f'<span class="sr" id="sr-{ik}" style="color:{rc}">{rl}</span>'
            f'<span class="sp" id="sp-{ik}">백분위 {a["pct"]*100:.0f}%</span></div></div>'
            f'<script>window.SCDIST=window.SCDIST||{{}};window.SCDIST["{ik}"]={_scdist};'
            f'window.SCBASE=window.SCBASE||{{}};window.SCBASE["{ik}"]={a["cur"]:.4f};'
            f'window.CBIN=window.CBIN||{{}};window.CBIN["{ik}"]={a["cbin"]};'
            f'window.QEDGES=window.QEDGES||{{}};window.QEDGES["{ik}"]={_edges};'
            f'window.BINRET=window.BINRET||{{}};window.BINRET["{ik}"]={_bins};'
            f'window.BINMH=window.BINMH||{{}};window.BINMH["{ik}"]={_binmh};'
            f'window.PJBIN=window.PJBIN||{{}};window.PJBIN["{ik}"]={_pjb};</script>'
            f'<div class="expbar"><span class="exp-lab">이 국면의 향후 1년 실측</span>'
            f'<span class="exp-m" id="em-{ik}" style="color:{mcol}">평균 {m12:+.0%}</span>'
            f'<span class="exp-w" id="ew-{ik}">상승확률 {w12:.0%}</span>'
            f'<span class="exp-n">(과거 같은 점수구간 n={a["tbl"].get("n12", "")})</span></div>'
            f'{proj_html}'
            f'<div class="strip">{dist_strip(a["sc"], a["cur"], rc)}</div>'
            f'<div class="card"><h2>현재 국면의 기대수익</h2>'
            f'{render_forward(a["tbl"], a["cbin"], a["sc"], ik)}</div>'
            f'<div class="card"><h2>신호 분해 <span class="h2-sub">(체크 해제 시 종합점수에서 제외)</span></h2>'
            f'{render_signals(a["reads"], a["idx"])}</div></div>')

def kelly_backtest(idx='KOSPI', start='2010-12-31', H=12):
    """신호의 예측력이 가장 강한 12개월 지평에 맞춘 워크포워드 백테스트.
       매월 '지금 사서 12개월 보유' 결정을 내리고, 12개 시작월 코호트로 나눠
       각 코호트를 연 1회 리밸런싱으로 굴린 뒤 성과를 평균한다(표본 부족 완화).
       가중치·구간·μ·σ는 매 시점 과거 데이터만으로 재계산."""
    P = df[f'{idx}_종가'].dropna()
    rH = P.pct_change(H).shift(-H)
    rfH = (df['국고채10년'] / 100 * (H / 12)).reindex(P.index).ffill()
    yH = np.log(P.shift(-H) / P)
    sig = signals_for(idx); Z = {}
    for n, s_, base, *_ in sig:
        xy = pd.concat([ez(s_) * base, yH], axis=1, sort=True).dropna()
        r = xy.iloc[:, 0].corr(xy.iloc[:, 1]) if len(xy) > 40 else 0
        Z[n] = ez(s_) * (base if r >= 0 else -base)
    Z = pd.DataFrame(Z).ffill(limit=3)
    # 시작 시점을 고정하지 않는다. 신호가 60개월 이상 쌓인 뒤부터 자동으로 시작.
    _start = pd.Timestamp(start) if start else Z.dropna(how='all').index.min()
    cache, rows = {}, []
    for t in Z.dropna(how='all').index:
        if t < _start: continue
        hist = Z.loc[:t]; yh = yH.loc[:t].dropna()
        common = hist.index.intersection(yh.index)
        if len(common) < 60: continue
        if t.year not in cache:
            w = _ridge_weights(hist.loc[common], yh.loc[common], list(Z.columns))
            if w is None:
                _ic = pd.Series({c: abs(hist.loc[common, c].corr(yh.loc[common])) for c in Z.columns})
                w = _ic / _ic.sum() if _ic.sum() else _ic
            cache[t.year] = w
        w = cache[t.year]
        sh = (hist[w.index] * w).sum(axis=1, min_count=1).dropna()
        if len(sh) < 60: continue
        cur = sh.iloc[-1]; edges = np.quantile(sh.iloc[:-1], [.2, .4, .6, .8])
        b = int(np.digitize([cur], edges)[0])
        pct = float((sh.iloc[:-1] < cur).mean())
        past = pd.concat([sh.rename('s'), rH.reindex(sh.index).rename('r'),
                          rfH.reindex(sh.index).rename('rf')], axis=1, sort=True).dropna()
        past = past[past.index < t]
        g = past[np.digitize(past['s'], edges) == b]
        f = 0.0
        if len(g) >= 8:
            # 화면 계산과 동일하게 경험분포 켈리 (근거: _kelly_empirical 주석)
            f = _kelly_empirical((g['r'] - g['rf']).values)
        rows.append(dict(date=t, f=f, pct=pct, r=rH.get(t, np.nan), rf=rfH.get(t, np.nan)))
    B = pd.DataFrame(rows).set_index('date').dropna(subset=['r'])
    if len(B) < 24: return None

    def cohort(wfunc, lab):
        res = []
        for st in range(12):
            ix = B.index[st::12]
            if len(ix) < 5: continue
            sub = B.loc[ix]; w = wfunc(sub)
            w = pd.Series(w, index=sub.index) if np.isscalar(w) else w
            port = w * sub['r'] + (1 - w) * sub['rf']
            if (1 + port).min() <= 0:
                res.append((float('nan'), -1.0, float('nan'))); continue
            eq = (1 + port).cumprod()
            res.append((eq.iloc[-1] ** (1 / len(port)) - 1,
                        float((eq / eq.cummax() - 1).min()), float(w.mean())))
        cg = [x[0] for x in res if x[0] == x[0]]
        return dict(lab=lab, cagr=float(np.mean(cg)) if cg else float('nan'),
                    lo=float(np.min(cg)) if cg else float('nan'),
                    hi=float(np.max(cg)) if cg else float('nan'),
                    mdd=float(np.mean([x[1] for x in res])),
                    avg=float(np.nanmean([x[2] for x in res])),
                    bust=sum(1 for x in res if x[0] != x[0]))

    return dict(span=(B.index[0], B.index[-1]), n=len(B), H=H, rows=[
        cohort(lambda s: 1.0, '1. 바이&홀드 (100%)'),
        cohort(lambda s: s['f'], '2. 켈리 (상한 없음)'),
        cohort(lambda s: s['f'] / 2, '3. 하프켈리 (상한 없음)'),
        cohort(lambda s: s['f'].clip(0, 1), '4. 켈리 0~100% 제한'),
        cohort(lambda s: s['pct'], '5. 점수백분위 비중'),
        cohort(lambda s: 0.5, '6. 고정 50:50'),
        cohort(lambda s: 0.7, '7. 고정 70:30')],
        fstat=dict(med=float(B['f'].median()), lo=float(B['f'].min()), hi=float(B['f'].max()),
                   shortpct=float((B['f'] < 0).mean()), levpct=float((B['f'] > 2).mean())))

def bet_backtest(idx='KOSPI', start=None):
    """백분위→베팅(-50~+150%) 방식의 12개월 워크포워드 백테스트(12 코호트 평균)."""
    P = df[f'{idx}_종가'].dropna()
    rH = P.pct_change(12).shift(-12); rfH = (df['국고채10년'] / 100).reindex(P.index).ffill()
    yH = np.log(P.shift(-12) / P)
    sig = signals_for(idx); Z = {}
    for n, s_, base, *_ in sig:
        xy = pd.concat([ez(s_) * base, yH], axis=1, sort=True).dropna()
        r = xy.iloc[:, 0].corr(xy.iloc[:, 1]) if len(xy) > 40 else 0
        Z[n] = ez(s_) * (base if r >= 0 else -base)
    Z = pd.DataFrame(Z).ffill(limit=3)
    cache, rows = {}, []
    for t in Z.dropna(how='all').index:
        if t < pd.Timestamp(start): continue
        hist = Z.loc[:t]; yh = yH.loc[:t].dropna()
        common = hist.index.intersection(yh.index)
        if len(common) < 60: continue
        if t.year not in cache:
            w = _ridge_weights(hist.loc[common], yh.loc[common], list(Z.columns))
            if w is None:
                _ic = pd.Series({c: abs(hist.loc[common, c].corr(yh.loc[common])) for c in Z.columns})
                w = _ic / _ic.sum() if _ic.sum() else _ic
            cache[t.year] = w
        w = cache[t.year]; sh = (hist[w.index] * w).sum(axis=1, min_count=1).dropna()
        if len(sh) < 60: continue
        pct = float((sh.iloc[:-1] < sh.iloc[-1]).mean())
        # 전통적 켈리: 과거 같은 국면의 승률·손익비로 f* = p − q/b
        past = pd.concat([sh.rename('s'), rH.reindex(sh.index).rename('r')], axis=1, sort=True).dropna()
        past = past[past.index < t]
        kf = 0.0
        if len(past) >= 40:
            e = np.quantile(past['s'], [.2, .4, .6, .8])
            kb = int(np.digitize([sh.iloc[-1]], e)[0])
            lab = np.digitize(past['s'], e)
            fs, ns = [], []
            for bb_ in range(5):
                g = past['r'][lab == bb_]
                if len(g) < 4:
                    fs.append(np.nan); ns.append(0); continue
                w_, l_ = g[g > 0], g[g <= 0]
                p_ = len(w_) / len(g); q_ = 1 - p_
                aw = float(w_.mean()) if len(w_) else 0.0
                al = float(abs(l_.mean())) if len(l_) else 0.0
                if al > 0 and aw > 0: v = p_ - q_ / (aw / al)
                elif al == 0:         v = 1.5
                else:                 v = -0.5
                fs.append(v); ns.append(len(g))
            ok = [i for i in range(5) if ns[i] > 0]
            if len(ok) >= 2:
                sm = _isotonic([fs[i] for i in ok], [ns[i] for i in ok])   # 단조 제약
                fmap = {ok[i]: sm[i] for i in range(len(ok))}
                kf = fmap.get(kb, 0.0)
        rows.append(dict(date=t, pct=pct, kf=max(-0.5, min(1.5, kf)),
                         r=rH.get(t, np.nan), rf=rfH.get(t, np.nan)))
    B = pd.DataFrame(rows).set_index('date').dropna(subset=['r'])
    if len(B) < 24: return None

    def cohort(wf, lab):
        res = []
        for st in range(12):
            ix = B.index[st::12]
            if len(ix) < 5: continue
            sub = B.loc[ix]; w = wf(sub); w = pd.Series(w, index=sub.index) if np.isscalar(w) else w
            port = w * sub['r'] + (1 - w) * sub['rf']
            if (1 + port).min() <= 0: res.append((float('nan'), -1.0)); continue
            eq = (1 + port).cumprod()
            res.append((eq.iloc[-1] ** (1 / len(port)) - 1, float((eq / eq.cummax() - 1).min())))
        cg = [x[0] for x in res if x[0] == x[0]]
        return dict(lab=lab, cagr=float(np.mean(cg)) if cg else float('nan'),
                    lo=float(np.min(cg)) if cg else float('nan'),
                    mdd=float(np.mean([x[1] for x in res])),
                    bust=sum(1 for x in res if x[0] != x[0]))
    return dict(span=(B.index[0], B.index[-1]), n=len(B), rows=[
        cohort(lambda s: 1.0, '바이&홀드 (100%)'),
        cohort(lambda s: s['kf'], '켈리 f*=p−q/b (−50~+150%)'),
        cohort(lambda s: s['kf'].clip(0, 1), '켈리 + 0~100% 제한'),
        cohort(lambda s: (-0.5 + s['pct'] * 2.0), '백분위→ −50~+150%'),
        cohort(lambda s: 0.5, '고정 50:50'),
        cohort(lambda s: 0.7, '고정 70:30')])

# ── 계절 오버레이 ────────────────────────────────────────────────────────
_SEA_CACHE = {}


def season_pack(idx):
    """계절 통계 + 켈리 계절조정치. season_core 가 없으면 None.

    켈리 앵커는 상하한을 ±150%/−50% 가 아니라 넓게(−300%~+800%) 잡고 구한다.
    좁게 자르면 f_전체가 상한에 붙어 계절 효과가 통째로 사라진다(코스피 f_전체=+1.50 포화).
    """
    if not HAS_SEASON:
        return None
    if idx in _SEA_CACHE:
        return _SEA_CACHE[idx]
    cut = SEA.last_complete_month(_d.index)
    r = SEA.monthly_returns(df[f'{idx}_종가'], cut)
    anch = SEA.kelly_anchors(df[f'{idx}_종가'], df['국고채10년'], cut=cut, h=6,
                             kelly_fn=lambda v: _kelly_empirical(v, 0.0, -3.0, 8.0, 441))
    today = pd.Timestamp.today()
    ent = today.to_period('M').to_timestamp('M')   # '이번 달 말에 진입하면' 기준
    p = dict(cut=cut, r=r, tbl=SEA.month_table(r), ws=SEA.winter_vs_summer(r),
             sy=SEA.season_years(r), sub=SEA.subperiods(r, cut), anch=anch,
             dl=SEA.season_delta(anch, ent), now=SEA.season_now(today), ent=ent)
    _SEA_CACHE[idx] = p
    return p


def season_kelly_row(a):
    """켈리 표 아래 붙는 계절조정 한 줄. (HTML, 조정된 f) 반환."""
    p = season_pack(a['idx'])
    if p is None:
        return '', None
    bt = a['bet']
    base = bt['now']
    adj = max(bt['kmin'], min(bt['kmax'], base + p['dl']['adj']))
    wfp = p['dl']['wf'] * 100
    d = p['dl']['adj']
    cc = '#3fb37f' if adj > 0 else '#e5484d'
    arrow = '▲' if d > 0 else ('▼' if d < 0 else '–')
    ac = '#3fb37f' if d > 0 else ('#e5484d' if d < 0 else '#8b98ab')
    cap = ('상하한에 걸려 잘림' if abs(base + p['dl']['adj'] - adj) > 1e-9 else '')
    return (f'<div class="skrow">'
            f'<div class="sk-l">계절 조정 <span class="dim">(향후 6개월 진입 기준)</span></div>'
            f'<div class="sk-v" style="color:{cc}">{adj*100:+.0f}%</div>'
            f'<div class="sk-d">기본 {base*100:+.0f}% <span style="color:{ac}">{arrow} '
            f'{d*100:+.0f}%p</span><br><span class="dim">겨울비중 {wfp:.0f}% · '
            f'기울기 {p["anch"]["slope"]:+.2f}/겨울비중 · 축소 {SEA.SHRINK:.1f}배'
            f'{" · " + cap if cap else ""}</span></div></div>'), adj


def _sea_spark(tbl, w=250, h=52):
    """월별 평균수익 미니 막대 — 겨울 초록 / 여름 빨강"""
    vals = [t['mean'] for t in tbl]
    lo, hi = min(min(vals), 0), max(max(vals), 0)
    rng = (hi - lo) or 1
    lo -= rng * .12; hi += rng * .12; rng = hi - lo
    Y = lambda v: (hi - v) / rng * h
    bw = w / 12
    out = [f'<svg viewBox="0 0 {w} {h}" class="seaspark">']
    out.append(f'<line x1="0" x2="{w}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" stroke="#3a465a"/>')
    for i, t in enumerate(tbl):
        x = i * bw + bw * .17
        y0, y1 = Y(max(t['mean'], 0)), Y(min(t['mean'], 0))
        c = '#3fb37f' if t['winter'] else '#e5484d'
        out.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw*.66:.1f}" '
                   f'height="{max(y1-y0,0.6):.1f}" fill="{c}" rx="1.5">'
                   f'<title>{t["name"]} 평균 {t["mean"]:+.2f}% · 승률 {t["win"]:.0f}%</title></rect>')
    out.append('</svg>')
    return ''.join(out)


def season_section(AK, AQ):
    if not HAS_SEASON:
        return ''
    P = {a['idx']: season_pack(a['idx']) for a in (AK, AQ)}
    if any(v is None for v in P.values()):
        return ''
    now = P['KOSPI']['now']
    ncls = 'ok' if now['winter'] else 'bad'

    cols = ''
    for lab, a in (('코스피', AK), ('코스닥', AQ)):
        p = P[a['idx']]
        ws, sy = p['ws'], p['sy']
        rec = p['sub'][-2] if len(p['sub']) >= 2 else p['sub'][-1]     # 최근 10년
        skr, _ = season_kelly_row(a)
        # 월별 승률 한 줄 요약
        best = max(p['tbl'], key=lambda t: t['mean']); worst = min(p['tbl'], key=lambda t: t['mean'])
        cols += (f'<div class="seac"><div class="seac-h">{lab}</div>'
                 f'{_sea_spark(p["tbl"])}'
                 f'<div class="seagrid">'
                 f'<div><span class="k">11~4월 «천국»</span>'
                 f'<span class="v" style="color:#3fb37f">{ws["w"]["ann"]:+.1f}%<small>/년</small></span>'
                 f'<span class="c">월평균 {ws["w"]["mean"]:+.2f}% · 승률 {ws["w"]["win"]:.0f}%</span></div>'
                 f'<div><span class="k">5~10월 «지옥»</span>'
                 f'<span class="v" style="color:#e5484d">{ws["s"]["ann"]:+.1f}%<small>/년</small></span>'
                 f'<span class="c">월평균 {ws["s"]["mean"]:+.2f}% · 승률 {ws["s"]["win"]:.0f}%</span></div>'
                 f'<div><span class="k">격차 · 유의성</span>'
                 f'<span class="v">{ws["diff"]:+.2f}<small>%p/월</small></span>'
                 f'<span class="c">t={ws["t"]:.2f} · p={ws["p"]:.4f}</span></div>'
                 f'<div><span class="k">겨울이 이긴 해</span>'
                 f'<span class="v">{sy["beat"]}<small>/{sy["nyr"]}</small></span>'
                 f'<span class="c">최근10년 격차 {rec["diff"]:+.2f}%p (p={rec["p"]:.3f})</span></div>'
                 f'</div>'
                 f'<div class="seabw">최고 <b>{best["name"]} {best["mean"]:+.2f}%</b> · '
                 f'최저 <b>{worst["name"]} {worst["mean"]:+.2f}%</b></div>'
                 f'{skr}</div>')

    kk, kq = P['KOSPI'], P['KOSDAQ']
    return (f'<div class="sec"><div class="sec-head">'
            f'<div class="sec-t">계절 오버레이 <span class="sec-px">참고지표 · 종합점수 미반영</span></div>'
            f'<div class="ctrls"><span class="dbadge {ncls}"><b>지금은 {now["label"]}</b></span>'
            f'<button class="btn" onclick="toggleSE()">자세히 보기/숨기기</button></div></div>'
            f'<div class="card">'
            f'<div class="seabar"><div><span class="k">현재 구간</span>'
            f'<span class="v {ncls}">{now["label"]}</span></div>'
            f'<div><span class="k">{now["nextlabel"]}까지</span>'
            f'<span class="v">{now["days"]}일 <small>({now["next"]:%Y-%m-%d})</small></span></div>'
            f'<div><span class="k">이번 달 말 진입 시 겨울비중</span>'
            f'<span class="v">{kk["dl"]["wf"]*100:.0f}%<small>/6개월</small></span></div>'
            f'<div><span class="k">켈리 계절조정</span>'
            f'<span class="v">코스피 {kk["dl"]["adj"]*100:+.0f}%p · 코스닥 {kq["dl"]["adj"]*100:+.0f}%p</span></div>'
            f'</div>'
            f'<div class="seacols">{cols}</div>'
            f'<div id="seWrap" style="display:none">'
            f'<p class="note"><b>무엇인가.</b> "코스피·코스닥은 5~10월 지옥, 11~4월 천국"이라는 '
            f'속설(핼러윈 효과)을 보유 데이터로 검정한 결과입니다. 실제로 사실이었습니다 — '
            f'{kk["r"].index[0]:%Y}년 이후 지수 상승분이 사실상 전부 11~4월에서 나왔고, '
            f'5~10월은 누적으로 코스피 {kk["ws"]["s"]["cum"]:+.0f}% · 코스닥 {kq["ws"]["s"]["cum"]:+.0f}%입니다. '
            f'여름에 몰린 대형 급락(IMF·닷컴·금융위기·코로나)을 전부 빼도, 상하 10%를 잘라낸 '
            f'절사평균으로도 격차가 남습니다.</p>'
            f'<p class="note"><b>왜 종합점수에 넣지 않았나.</b> 이 모델의 예측지평은 12개월입니다. '
            f'12개월 창은 어느 달에 시작하든 12개 달을 <b>전부</b> 담기 때문에 계절성이 정의상 상쇄됩니다. '
            f'실측해도 진입월별 12개월 수익 차이는 코스피 p=0.76 · 코스닥 p=0.93으로 IC가 0입니다. '
            f'신호로 넣으면 |IC|≥0.10 필터에서 어차피 탈락하고, 억지로 넣으면 다른 신호의 가중만 갉아먹습니다. '
            f'그래서 <b>가중치 0의 참고지표</b>로 두었습니다 — 시가총액/M2나 M2 증가율과 같은 취급입니다.</p>'
            f'<p class="note"><b>대신 어디에 쓰나 — 켈리 진입 타이밍.</b> 지평을 6개월로 좁히면 계절성이 살아납니다. '
            f'그리고 종합점수와의 상관이 코스피 +0.02 · 코스닥 +0.04로 <b>사실상 직교</b>합니다. '
            f'기존 15개 신호(밸류·금리·환율·경기·변동성·레버리지)가 재지 않는 축이라, 종합점수를 '
            f'대체하지 않고 <b>더합니다</b>. 그래서 베팅비율 표에 <b>계절 조정</b> 한 줄을 붙였습니다:<br>'
            f'&nbsp;&nbsp;<b>조정 f* = 기본 f* + 축소계수 × 기울기 × (겨울비중 − 0.5)</b><br>'
            f'겨울비중은 지금 진입했을 때 향후 6개월 중 11~4월이 차지하는 몫입니다(0.5면 조정 0). '
            f'기울기는 겨울우세 창과 여름우세 창의 6개월 켈리 차이에서 나온 실측값입니다'
            f'(코스피 {kk["anch"]["slope"]:+.2f} · 코스닥 {kq["anch"]["slope"]:+.2f}). '
            f'축소계수 {SEA.SHRINK:.1f}은(는) 예측밴드의 국면프리미엄과 같은 관례로, 과거 강도의 절반만 반영합니다. '
            f'<span class="dim">비율(승수)이 아니라 가산(%p)인 이유: 코스닥 6개월 켈리 전체값이 '
            f'{kq["anch"]["all"]["f"]:+.2f}로 0 근처라 비율을 쓰면 13배로 폭발합니다.</span></p>'
            f'<div class="rawscroll"><table class="raw kt"><thead><tr><th>지수</th><th>6개월 창</th>'
            f'<th>n</th><th>승률 p</th><th>손익비 b</th><th>평균 μ</th><th>σ</th><th>켈리 f*</th>'
            f'</tr></thead><tbody>'
            + ''.join(
                ''.join(f'<tr{" class=here" if key=="win" else ""}><td>{lab if key=="all" else ""}</td>'
                        f'<td>{nm}</td><td class="dim">{P[ik]["anch"][key]["n"]}</td>'
                        f'<td>{P[ik]["anch"][key]["p"]:.1f}%</td>'
                        f'<td>{P[ik]["anch"][key]["b"]:.2f}</td>'
                        f'<td>{P[ik]["anch"][key]["mu"]:+.2f}%</td>'
                        f'<td class="dim">{P[ik]["anch"][key]["sd"]:.1f}%</td>'
                        f'<td style="font-weight:600">{P[ik]["anch"][key]["f"]:+.2f}</td></tr>'
                        for key, nm in (('all', '전체'), ('win', '겨울 우세 (겨울비중≥2/3)'),
                                        ('sum', '여름 우세 (겨울비중≤1/3)')))
                for ik, lab in (('KOSPI', '코스피'), ('KOSDAQ', '코스닥')))
            + f'</tbody></table></div>'
            f'<p class="note kwarn"><b>한계.</b> ① 코스피는 최근 10년 p={kk["sub"][-2]["p"]:.2f}로 '
            f'유의하지 않습니다 — 강하게 남아있는 쪽은 코스닥(p={kq["sub"][-2]["p"]:.3f})입니다. '
            f'② 바로 직전 2025년 여름은 코스피 +60.7% · 코스닥 +25.5%로 정반대였습니다. '
            f'계절성은 평균의 이야기이지 매년의 약속이 아닙니다. '
            f'③ 널리 알려진 아노말리라 차익거래로 소멸할 수 있습니다. '
            f'④ 가격지수 기준이라 배당(4월 전후 배당락)은 반영되지 않았습니다. '
            f'이런 이유로 조정 폭을 절반으로 축소했고, 종합점수 자체는 건드리지 않습니다.</p>'
            f'<p class="note" style="margin-bottom:0">월별 표·시즌별 연도·백테스트 등 전체 검증은 '
            f'<a class="slink" id="seaLink" href="season.html">계절성 전용 대시보드</a>에 있습니다.</p>'
            f'</div></div></div>')


def kelly_section(AK, AQ):
    def block(lab, a):
        bt = a['bet']; nb = bt['now']; ck = bt['cur_kb']
        cc = '#3fb37f' if nb > 0 else '#e5484d'
        rows = ''
        for k, r in enumerate(bt['rows']):
            here = 'here' if k == ck else ''
            if r['n'] == 0:
                rows += f'<tr class="{here}"><td>{r["nm"]}</td><td colspan="10" class="dim">표본 없음</td></tr>'
                continue
            bb = '∞' if r['b'] == float('inf') else f'{r["b"]:.2f}'
            c1 = '#3fb37f' if r['fc'] > 0 else '#e5484d'
            c2 = '#3fb37f' if r['fcontc'] > 0 else '#e5484d'
            d1 = '<sup>†</sup>' if abs(r['f_adj'] - r['f']) > 1e-9 else ''
            d2 = '<sup>†</sup>' if abs(r['fcont_adj'] - r['fcont']) > 1e-9 else ''
            s1 = '*' if abs(r['f_adj'] - r['fc']) > 1e-9 else ''
            s2 = '*' if abs(r['fcont_adj'] - r['fcontc']) > 1e-9 else ''
            rows += (f'<tr class="{here}"><td>{r["nm"]}</td>'
                     f'<td>{r["p"]*100:.0f}%</td><td class="dim">{r["q"]*100:.0f}%</td>'
                     f'<td>{r["aw"]*100:+.1f}%</td><td>{r["al"]*100:.1f}%</td><td>{bb}</td>'
                     f'<td style="color:{c1};font-weight:600;border-right:1px solid #2b3648">'
                     f'{r["fc"]*100:+.0f}%{s1}{d1}</td>'
                     f'<td>{r["mu"]*100:+.1f}%</td><td>{r["sd"]*100:.1f}%</td>'
                     f'<td class="dim">{r["rf"]*100:.1f}%</td>'
                     f'<td style="color:{c2};font-weight:600">{r["fcontc"]*100:+.0f}%{s2}{d2}</td>'
                     f'<td class="dim">{r["n"]}</td></tr>')
        cr = bt['rows'][ck] if bt['rows'] else None
        sub = ''
        if cr and cr['n']:
            bb = '∞' if cr['b'] == float('inf') else f'{cr["b"]:.2f}'
            sub = (f'<div class="kb-sub">'
                   f'<b>① 단순 켈리</b>  p {cr["p"]*100:.0f}% · q {cr["q"]*100:.0f}% · '
                   f'평균이익 {cr["aw"]*100:+.1f}% · 평균손실 {cr["al"]*100:.1f}% · 손익비 b {bb}<br>'
                   f'&nbsp;&nbsp;f* = p − q/b = <b>{cr["f"]*100:+.0f}%</b>'
                   f'{" → 보정 " + format(cr["fc"]*100, "+.0f") + "%" if abs(cr["f"]-cr["fc"])>1e-9 else ""}<br>'
                   f'<b>② 연속형 켈리</b>  μ {cr["mu"]*100:+.1f}% · '
                   f'σ<sub>하방</sub> {cr["sd_dn"]*100:.1f}% '
                   f'<span class="dim">(전체 σ {cr["sd"]*100:.1f}%)</span> · '
                   f'무위험 {cr["rf"]*100:.1f}%<br>'
                   f'&nbsp;&nbsp;경험분포 최적 f* = <b>{cr["fcont"]*100:+.0f}%</b>'
                   f'{" → 보정 " + format(cr["fcontc"]*100, "+.0f") + "%" if abs(cr["fcont"]-cr["fcontc"])>1e-9 else ""}'
                   f' · 표본 {cr["n"]}개(독립 약 {max(1,cr["n"]//12)}개)</div>')
        skr, _ = season_kelly_row(a)
        return (f'<div class="kb"><div class="kb-h">{lab}</div>'
                f'<div class="kb-big" style="color:{cc}">{nb*100:+.0f}%</div>'
                f'<div class="kb-cap">현재 국면({bt["rows"][ck]["nm"] if bt["rows"] else "-"}) · '
                f'단순 켈리 기준 <span class="dim">(연속형 '
                f'{bt["rows"][ck]["fcontc"]*100:+.0f}%)</span></div>'
                f'{skr}'
                f'{sub}'
                f'<div class="rawscroll"><table class="raw kt"><thead>'
                f'<tr><th rowspan="2">국면</th>'
                f'<th colspan="6" class="grp">① 단순 켈리  f* = p − q/b</th>'
                f'<th colspan="4" class="grp">② 연속형 켈리  경험분포 E[log] 최대화</th>'
                f'<th rowspan="2">n</th></tr>'
                f'<tr><th>p(승)</th><th>q(패)</th><th>평균이익</th><th>평균손실</th>'
                f'<th>손익비 b</th><th class="bd">f*</th>'
                f'<th>μ(평균)</th><th>σ(표준편차)</th><th>rf</th><th>f*</th></tr>'
                f'</thead><tbody>{rows}</tbody></table></div>'
                f'<div class="kb-note">† 단조 보정 · * 상하한(+150%/−50%) 적용</div></div>')

    bt = bet_backtest()
    btml = ''
    if bt:
        trs = ''
        for r in bt['rows']:
            hl = ' class="best"' if '150%' in r['lab'] or '0~100%' in r['lab'] else ''
            cg = 'n/a' if r['cagr'] != r['cagr'] else f"{r['cagr']*100:.2f}%"
            lo = 'n/a' if r['lo'] != r['lo'] else f"{r['lo']*100:.2f}%"
            trs += (f'<tr{hl}><td>{r["lab"]}</td><td>{cg}</td><td class="dim">{lo}</td>'
                    f'<td style="color:#e5484d">{r["mdd"]*100:.1f}%</td><td class="dim">{r["bust"]}/12</td></tr>')
        bh = bt['rows'][0]; mp = bt['rows'][1]; cp = bt['rows'][2]
        btml = (f'<h3 class="bt-h">백테스트 — 백분위 베팅이 실제로 통했는가</h3>'
                f'<p class="note" style="margin:0 0 10px"><b>기간</b> {bt["span"][0].strftime("%Y-%m")}~'
                f'{bt["span"][1].strftime("%Y-%m")} (결정 {bt["n"]}회) · <b>보유·리밸런싱</b> 12개월 · '
                f'12개 시작월 코호트 평균 · 매 시점 과거 데이터만 사용 · 거래비용·세금 미반영.</p>'
                f'<div class="rawscroll"><table class="raw kt bt"><thead><tr><th>전략</th><th>CAGR(평균)</th>'
                f'<th>최저코호트</th><th>MDD</th><th>파산</th></tr></thead><tbody>{trs}</tbody></table></div>'
                f'<p class="note" style="margin-top:10px"><b>결과.</b> 백분위→−50~+150% 방식은 '
                f'CAGR {mp["cagr"]*100:.2f}% / MDD {mp["mdd"]*100:.1f}%로, 바이&홀드'
                f'({bh["cagr"]*100:.2f}% / {bh["mdd"]*100:.1f}%)를 <b>수익·낙폭 양쪽에서</b> 앞섰습니다. '
                f'레버리지·공매도가 부담되면 0~100% 제한판({cp["cagr"]*100:.2f}% / {cp["mdd"]*100:.1f}%)도 '
                f'바이&홀드보다 우수합니다.</p>')
    return (f'<div class="sec"><div class="sec-head"><div class="sec-t">베팅비율 (종합점수 기반)</div>'
            f'<div class="ctrls"><button class="btn" onclick="toggleK()">계산 보기/숨기기</button></div></div>'
            f'<div class="card" id="kWrap" style="display:none">'
            f'<p class="note"><b>전통적 켈리 공식</b>으로 베팅비율을 산출합니다: '
            f'<b>f* = (bp − q) / b = p − q/b</b><br>'
            f'· <b>p</b> = 이길 확률 — 현재와 같은 국면에서 이후 12개월 수익이 플러스였던 비율<br>'
            f'· <b>q</b> = 질 확률 (1 − p)<br>'
            f'· <b>b</b> = 손익비 — 이겼을 때 평균수익 ÷ 졌을 때 평균손실<br>'
            f'국면은 종합점수를 5등분해 나누고, <b>현재 점수를 그 경계에 대입해</b> 지금 어느 국면인지 판정합니다. '
            f'결과값은 <b>+150% ~ −50%</b>로 제한합니다(양수=매수, 100% 초과=레버리지, 음수=축소·공매도). '
            f'진 적이 없는 국면은 b가 무한대가 되어 상한 +150%가 적용됩니다.</p>'
            f'<p class="note" style="margin-top:0"><b>두 가지 켈리를 나란히 보여줍니다.</b><br>'
            f'<b>① 단순 켈리 f* = p − q/b</b> — 결과를 이겼다/졌다로만 나눕니다. '
            f'도박에서 쓰는 원형이고 직관적이지만, 이겼을 때가 <i>얼마나</i> 흔들렸는지는 무시합니다.<br>'
            f'<b>② 연속형 켈리 — 경험분포 E[log] 최대화</b> — 과거 같은 국면의 '
            f'수익 분포를 <b>그대로 써서</b> 기대로그성장이 가장 큰 비중을 찾습니다. '
            f'흔히 쓰는 f*=(μ−rf)/σ² 는 로그효용의 2차 근사라 사실상 정규분포를 '
            f'전제하는데, 12개월 수익도 완전한 정규는 아닙니다(초과첨도 +1.9~3.0). '
            f'경험분포 방식은 분포 가정이 없고, 파산 구간에서 log가 −∞로 발산해 '
            f'과베팅을 스스로 막습니다. 손실 위험이 큰 국면에서 자동으로 비중을 줄이므로 '
            f'주식처럼 결과가 연속적인 자산에는 이쪽이 이론적으로 더 맞습니다. '
            f'다만 표본이 국면당 60여개뿐이라 값이 튈 수 있습니다(표에서 상하한에 자주 걸리는 이유).<br>'
            f'대시보드 상단의 큰 숫자는 <b>①</b> 기준이며, 괄호 안에 ②를 함께 표기합니다. '
            f'두 값이 크게 다르면 그 국면의 추정이 불안정하다는 신호로 보시면 됩니다.</p>'
            f'<p class="note kwarn" style="margin-top:0"><b>표본 한계와 단조 보정.</b> '
            f'각 국면의 관측치는 40여 개지만 12개월 수익이 서로 겹치므로 '
            f'<b>독립 표본은 3개 안팎</b>입니다. 이 정도면 승률의 표준오차가 ±28%p에 달해, '
            f'원식 f*를 그대로 쓰면 "불리"가 "중립"보다 높게 나오는 순서 뒤집힘이 생깁니다. '
            f'점수가 높을수록 기대수익이 높다는 것은 이 모델의 핵심 전제(12개월 IC 0.6 이상)이므로, '
            f'그 전제를 제약으로 걸어 <b>뒤집힌 인접 국면을 표본가중 평균으로 병합</b>했습니다'
            f'(단조증가 제약 회귀). 표에 원식 값과 적용값을 나란히 두었으니 보정 폭을 직접 확인하실 수 있습니다.</p>'
            f'<div class="kcols">{block("코스피", AK)}{block("코스닥", AQ)}</div>{btml}'
            f'<p class="note kwarn" style="margin-top:12px"><b>참고용 수치이며 투자 조언이 아닙니다.</b> '
            f'이 비중은 코스피·코스닥 지수만 보고 과거 통계로 만든 것이며, 개인의 나이·소득·부채·투자기간·'
            f'손실감내도를 전혀 반영하지 않습니다. 100% 초과 레버리지와 공매도는 상당한 추가 위험을 수반하고, '
            f'백테스트가 미래를 보장하지도 않습니다. 실제 배분은 본인 상황을 아는 자격 있는 전문가와 '
            f'상의해 결정하시기 바랍니다.</p></div></div>')

def wtable(a):
    order = sorted(a['ic'].keys(), key=lambda n: -a['w'][n])
    rows = ''
    for n in order:
        icv, wt = a['ic'][n], a['w'][n]
        eff, contra = a['direction'][n]
        dlab = ('낮을수록↑' if eff < 0 else '높을수록↑') + ('<span class="con"> 역발상</span>' if contra else '')
        rows += (f'<tr><td>{n}</td><td>{icv:.2f}</td>'
                 f'<td><div class="wbar"><span style="width:{wt/max(a["w"].values())*100:.0f}%"></span></div></td>'
                 f'<td>{wt*100:.0f}%</td><td class="dir">{dlab}</td></tr>')
    return (f'<table class="raw wt"><thead><tr><th>신호</th><th>단변량|IC|</th><th></th>'
            f'<th>최종가중</th><th>방향</th></tr></thead><tbody>{rows}</tbody></table>')

def weights_section(AK, AQ):
    return (f'<div class="sec"><div class="sec-head"><div class="sec-t">가중치 산출 근거</div>'
            f'<div class="ctrls"><button class="btn" onclick="toggleW()">근거 보기/숨기기</button></div></div>'
            f'<div class="card" id="wWrap" style="display:none">'
            f'<p class="note">후보 지표를 <b>전부</b> 넣고, <b>다변량 Ridge 회귀</b>(λ=10·30·100 앙상블)로 '
            f'12개월 뒤 수익률을 함께 설명하게 한 뒤, <b>각 신호의 단독 예측력(IC)을 Ridge 계수에 곱한 '
            f'혼합 가중</b>을 씁니다. 단변량 |IC|(표의 둘째 열)는 그 지표 <i>혼자</i>의 예측력이고, '
            f'Ridge 계수는 다른 지표와 <b>겹치는 부분을 제거한 뒤 남는 고유 기여</b>입니다. '
            f'이 둘을 곱하면 <b>"예측력도 있고 남들과 겹치지도 않는"</b> 신호가 높은 가중을 받습니다.<br>'
            f'<b>왜 IC×Ridge 혼합인가.</b> 순수 Ridge 계수만 쓰면 예측력이 거의 없는 신호'
            f'(예: 일드커브 IC 0.10, 기준금리 IC 0.14)가 회귀에서 <b>억제변수</b>로 작동해 '
            f'"다른 변수를 돕는 척" 가중을 부풀리는 문제가 있었습니다. 실제로 일드커브는 IC 순위 14위인데 '
            f'가중 7위였습니다. 여기에 IC를 곱하면 예측력 없는 신호는 자동으로 눌리고, 가치지표(PBR·예상PER)처럼 '
            f'실제 예측력 있는 신호가 제 몫을 받습니다. '
            f'<b>표본외 검증(2005–15 학습 → 2016–26 검증) 결과 표본외 IC가 순수 Ridge 0.61 → 혼합 0.71로 개선</b>됐습니다.<br>'
            f'<b>가중치는 여전히 IC 순서와 다를 수 있습니다.</b> 서로 비슷한 말을 하는 신호들(PBR·수출·경기선행지수는 '
            f'모두 "경기 과열"을 가리켜 상관됨)은 Ridge 단계에서 비중이 나뉘기 때문입니다. '
            f'즉 최종가중 = (혼자서 얼마나 맞히나) × (남들과 얼마나 겹치지 않나) ÷ (무리와 얼마나 뭉치나).<br>'
            f'<b>왜 매크로(환율·금리·경기선행)가 가치지표(PBR·PER)보다 가중이 높은가.</b> '
            f'이 모델은 "지금 싼가"가 아니라 <b>"향후 12개월 수익을 무엇이 잘 맞혔나"</b>만 봅니다. '
            f'과거 데이터에서는 매크로의 예측력(평균 IC 0.30)이 가치지표(평균 IC 0.23)보다 높았습니다 — '
            f'예컨대 환율·금리 방향은 12개월 시계에서 밸류에이션보다 지수를 잘 설명했습니다. '
            f'가치투자 관점에서는 PBR·예상PER이 더 중요하다고 볼 수 있지만, 그것은 이 모델이 '
            f'재는 <b>단기(12개월) 예측력</b>과는 다른 이야기입니다. 밸류는 방향은 맞혀도 '
            f'"언제"를 잘 못 맞히기 때문입니다. 이 대시보드는 어디까지나 "과거 통계가 무엇을 잘 맞혔나"를 '
            f'보여줄 뿐, "무엇이 투자에 더 중요한가"를 판정하지 않습니다.<br>'
            f'<b>상관벌점.</b> 서로 강하게 얽힌 신호 무리(예: 기준금리·기준금리YoY·일드커브가 상관 0.5~0.6)가 '
            f'집단으로 가중을 빨아들이는 것을 막기 위해, 각 신호를 다른 신호와의 평균상관으로 나눠 벌점을 줍니다'
            f'(표본외 IC 0.71→0.73 개선). 다만 한 신호와만 강하게 겹치는 경우는 평균이 희석되어 '
            f'완전히 걸러지지는 않습니다.<br>'
            f'<b>산출 절차.</b> ① 각 신호를 과거 데이터만으로 표준화(z-score) → ② 경제적 방향을 붙이되 '
            f'실제 데이터가 반대면 뒤집음(역발상 표시) → ③ 단변량 |IC| 0.10 미만은 예측력 없음으로 보고 제외 → '
            f'④ 남은 신호를 능형회귀(Ridge, λ=10·30·100 앙상블)에 넣어 회귀계수를 구하고 → '
            f'⑤ <b>|IC| × |Ridge계수| ÷ (1+평균상관)</b>을 합이 100%가 되도록 정규화한 것이 가중치입니다.<br>'
            f'<b>방향</b>은 과거 IC 부호로 확정하며, 통념과 반대면 '
            f'<span class="con">역발상</span>으로 표시합니다(예: ROE·수출 급증 = 경기 정점 → 이후 약세). '
            f'코스피·코스닥 각자 자기 데이터로 산출. 중첩표본이라 신뢰구간은 넓습니다.</p>'
            f'<div class="wcols"><div><h3>코스피</h3>{wtable(AK)}</div>'
            f'<div><h3>코스닥</h3>{wtable(AQ)}</div></div></div></div>')

GLOSSARY = [
    ('PBR (주가순자산비율)', '주가 ÷ 주당순자산. 회사가 가진 <b>순자산(장부가치) 대비 몇 배</b>에 거래되는지. '
     '1배면 장부가와 같은 값, 1배 미만이면 회사를 다 팔아 나눈 값보다 싸게 거래된다는 뜻. 낮을수록 저평가.'),
    ('PER (주가수익비율)', '주가 ÷ 주당순이익. <b>지금 이익으로 원금을 회수하는 데 몇 년</b> 걸리는지. '
     '10배면 10년치 이익 가격. 낮을수록 저평가지만, 불황에 이익이 급감하면 오히려 높아 보이는 착시가 있음.'),
    ('예상PER (Forward PER)', '주가 ÷ <b>앞으로 12개월 예상</b> 주당순이익(애널리스트 컨센서스). '
     '과거 실적이 아닌 미래 이익 기준이라, 이익이 급변하는 국면에서 후행 PER보다 현실을 잘 반영.'),
    ('ROE (자기자본이익률)', '순이익 ÷ 자기자본. <b>내 돈으로 얼마를 벌었나</b>를 나타내는 수익성 지표. '
     '높을수록 좋은 회사지만, 지수 전체로 보면 ROE 정점 = 이익 사이클 고점이라 이후 약세 신호가 되기도 함.'),
    ('일드갭', '주식의 이익수익률(=100÷PER) − 국고채 10년 금리. <b>주식이 채권보다 얼마나 매력적인가</b>. '
     '값이 클수록 채권 대비 주식이 싸다는 뜻. 이 대시보드는 코스피에 예상PER 기준을 사용.'),
    ('VKOSPI (코스피200 변동성지수)', '코스피200 <b>옵션 가격에서 뽑아낸 향후 30일 기대변동성</b>'
     '(내재변동성). 시장이 앞으로 얼마나 출렁일 것으로 보는지를 옵션 프리미엄이 말해줍니다. '
     '한국판 VIX가 바로 이것입니다(KRX 산출, 2003-01~). '
     '<b>[방향]</b> 실현변동성과 같이 <b>높을수록 강세로 고정</b>합니다 — "공포에 사라". '
     '상위 10%(공포 극단) 진입 후 이후 1년 <b>+22.2%(승률 86%)</b>, 전체평균 +9.3%(66%), '
     '하위 10%(안심 극단) +2.8%(57%)로 갈립니다. '
     '<b>[실현변동성과의 관계]</b> 수준 상관 0.890으로 함께 움직이지만, 실측상 '
     '<b>실현변동성이 VKOSPI를 4일 후행</b>합니다(최대상관 +0.914). 급락 직후엔 실현변동성이 '
     '지난 폭락을 20일간 끌고 다니는 반면 VKOSPI는 먼저 진정되므로 크게 벌어집니다 '
     '(2026-08-12 기준 실현 95.6 vs VKOSPI 56.5). 단독 예측력도 VKOSPI가 앞섭니다(IC 0.196 vs 0.181). '
     '<b>코스피 전용</b>이며(코스피200 옵션 기반), 코스닥은 자기 실현변동성을 씁니다.'),
    ('실현변동성(20일)', '코스피 <b>일간 등락폭 20일치로 계산한 연율화 변동성</b>'
     '(로그수익률 표준편차 × √252). 값이 클수록 시장이 요동쳤다는 뜻이고, '
     '극단적으로 높으면 패닉 국면 = 역사적으로 저가 매수 기회였습니다. '
     '<b>[VKOSPI와 다릅니다]</b> 예전엔 이 항목을 "한국VIX"로 표기했으나 오해를 부를 수 있어 이름을 바꿨습니다. '
     'VKOSPI는 코스피200 <b>옵션 가격에서 뽑아낸 향후 30일 기대변동성</b>(내재변동성)이고, '
     '이 지표는 <b>이미 일어난 등락</b>을 재는 실현변동성입니다. 급락 직후 국면에서는 '
     '실현변동성이 과거 폭락을 20일간 끌고 다니는 반면 VKOSPI는 먼저 진정되므로 '
     '두 값이 크게 벌어질 수 있습니다(2026-08-12 기준 실현변동성 95.6 vs VKOSPI 56.5). '
     'KRX가 2025년 말부터 통계를 로그인 뒤로 옮겨 VKOSPI 자동 수집이 막혀 있어, 현재는 '
     '실현변동성을 대용으로 씁니다.'),
    ('M2 증가율(YoY)', '광의통화(M2) 잔액의 전년동월 대비 증가율. <b>시중에 돈이 얼마나 빨리 늘고 있는가</b>. '
     '통화가 팽창하면 자산가격이 오르는 경향이 있어 대표적 경기 선행지표로 쓰인다. '
     'M2는 현금·요구불예금(M1)에 정기예적금·수익증권 등을 더한 넓은 통화량 지표.'),
    ('M2/M1 비율', '광의통화(M2) ÷ 협의통화(M1). <b>유동성의 회전 속도·성격</b>을 본다. '
     '비율이 높아지면 돈이 정기예금 등에 묶여 안 도는 것(위험회피), 낮아지면 즉시 쓸 수 있는 '
     '자금이 늘어 활발해지는 것으로 해석한다.'),
    ('시가총액/M2', '코스피 시가총액 ÷ 광의통화(M2). <b>통화량 대비 주식시장이 얼마나 비싼가</b>. '
     '유명한 버핏지표(시총/GDP)의 통화량 버전. 높으면 통화 대비 고평가, 낮으면 저평가. '
     '<b>[참고지표]</b> 단독 예측력은 IC 0.52로 최상위급이지만 PBR과 상관 0.84로 사실상 겹쳐, '
     '가중치에 넣어도 표본외 성능 기여가 0.006에 그친다. 게다가 M2 데이터가 2003년부터라 표본이 '
     '짧고 최근 급등해 값이 극단으로 치솟는다. 그래서 <b>종합점수에는 넣지 않고 차트로만 관찰</b>한다 '
     '(같은 밸류 정보는 PBR·예상PER이 담당).'),
    ('경기선행지수', '통계청이 발표하는 <b>경기 국면 지표</b>(순환변동치 기준 100 안팎). '
     '100 이상이면 경기 확장, 이하면 수축. 지수가 높다는 건 이미 좋다는 뜻이라, 역발상으로는 고점 신호. '
     '<b>[한계]</b> 이 지수의 구성항목에 <b>코스피가 포함</b>돼 있어, 주가로 주가를 예측하는 '
     '순환참조가 일부 존재합니다(실측: 선행지수 YoY와 코스피 YoY의 최대 상관 시점이 +1개월 — 코스피가 앞섬). '
     '따라서 이 신호의 예측력 일부는 "경기"가 아니라 <b>코스피 자체의 평균회귀</b>에서 나옵니다. '
     '회귀로 주가 성분을 제거해 보았으나, 코스피가 극단적으로 움직이는 구간에서 보정이 과도해져 '
     '과열 신호가 침체로 뒤집히는 문제가 있어 <b>신호 값 자체는 원본을 씁니다</b>. '
     '대신 <b>가중치 산정에 쓰는 IC만 순환참조분을 뺀 순수 경기정보로 낮춥니다</b>'
     '(원본 IC 0.565 → 코스피 성분 제거 후 0.421, 약 26%가 순환참조). '
     '이렇게 하면 극단 붕괴 없이 가중 과다만 교정됩니다.'),
    ('신용융자/예탁금', '신용융자 잔고 ÷ 투자자예탁금. <b>빚내서 산 돈을 대기 현금으로 나눈 투자자 레버리지</b>'
     '(금융투자협회 FreeSIS 일별). 높으면 빚으로 버티는 시장이라 작은 하락에도 반대매매가 연쇄되고, '
     '낮으면 팔 사람이 이미 판 상태입니다. <b>코스피 전용</b>(코스닥은 표본외 개선이 +0.002로 노이즈 수준이라 제외). '
     '<b>[2007년 이전 제외]</b> 2007년 신용공여 제도가 급성장하며 규모가 한 자릿수 배로 뛰었습니다'
     '(신용융자 2006년 0.47조 → 2007년 4.40조, 비율 0.043 → 0.339). 그 이전은 사실상 다른 시장이라 '
     '섞어서 평균을 내면 <b>지금이 최근 5년 중 최저 수준인데도 "불리"로 표시되는</b> 오류가 납니다. '
     '그래서 신호는 2007년 이후로만 계산하고, 차트에는 맥락으로 남기되 절단선을 그었습니다. '
     '<b>[강점]</b> 7일·1개월·3개월·6개월·1년 <b>다섯 구간 모두에서 유의</b>한 유일한 자금 신호입니다. '
     '다른 자금 지표는 단기엔 모멘텀(+), 장기엔 역발상(−)으로 부호가 뒤집혀 쓰기 어렵습니다. '
     '꼬리가 특히 강해서(2007~ 기준), 하위 5% 진입 시 이후 1년 <b>+30.4%(승률 96%)</b>, '
     '상위 5% 진입 시 <b>−13.3%(승률 14%)</b>로 갈립니다(6개월은 각각 +26.6%/승률 100%, −8.2%/승률 20%). '
     '전환점 적중도 좋아서 2011·2018·2021 고점에서 불리, 2020·2024 바닥에서 유리를 가리켰습니다. '
     '<b>[한계]</b> 단기 예측력의 크기 자체는 작습니다(7일 IC −0.08). 일간 자금 <i>변화</i>는 오히려 '
     '지수를 3일 <b>후행</b>하므로(교차상관 실측), 이 지표는 며칠 앞을 보는 망원경이 아니라 '
     '<b>시장이 얼마나 빚으로 버티고 있는지 재는 체온계</b>로 쓰는 것이 맞습니다. '
     '평상시엔 중립이고 극단(상·하위 10%)에서만 신호가 켜집니다.'),
    ('신용스프레드', '회사채(AA−, 3년) 금리 − 국고채(3년) 금리. <b>기업이 돈 빌릴 때 더 내는 웃돈</b>. '
     '벌어지면 신용 경색·불안, 좁으면 안정. 크게 벌어진 뒤엔 위험자산이 반등하는 경향.'),
    ('일드커브 (장단기 금리차)', '국고채 10년 − 3년 금리. <b>미래 경기에 대한 채권시장의 전망</b>. '
     '가팔라지면(스팁) 경기 회복 기대, 평평하거나 역전되면 침체 우려.'),
    ('수출 YoY', '통관 수출금액의 <b>전년 동월 대비 증가율</b>. 한국은 수출 의존도가 높아 기업 이익의 선행 지표. '
     '다만 급증 구간은 이미 사이클 정점인 경우가 많아 역발상 신호로 작동.'),
    ('환율 (원/달러)', '달러당 원화 가격. 오르면 원화 약세. <b>동시점에는 악재</b>(외국인 매도)지만, '
     '극단적 약세는 위기의 바닥 신호라 6~12개월 뒤엔 강한 반등이 따라오는 경향.'),
    ('z-score (σ)', '어떤 값이 <b>과거 평균에서 표준편차 몇 배만큼</b> 떨어져 있는지. '
     '+2σ면 역사적으로 매우 높은 수준(상위 약 2%). 단위가 다른 지표들을 같은 잣대로 비교하기 위해 사용.'),
    ('IC (정보계수)', '어떤 신호와 <b>12개월 뒤 실제 수익률의 상관계수</b>. 그 지표의 예측 성적표. '
     '0.2 이상이면 의미 있는 수준, 0에 가까우면 예측력이 없다는 뜻.'),
    ('백분위', '현재 값이 <b>과거 20년 중 몇 %보다 높은지</b>. 백분위 5%면 지난 20년 중 하위 5% 수준이라는 뜻.'),
    ('승률 (상승확률)', '과거에 같은 점수 구간이었을 때, <b>12개월 뒤 지수가 실제로 올랐던 비율</b>.'),
]

DESC = {
 'KOSPI_종가':'코스피 지수','KOSDAQ_종가':'코스닥 지수','KOSPI_시총':'코스피 시가총액',
 'KOSDAQ_시총':'코스닥 시가총액','KOSPI_PER':'코스피 후행 PER','KOSDAQ_PER':'코스닥 후행 PER',
 'KOSPI_PBR':'코스피 PBR','KOSDAQ_PBR':'코스닥 PBR','KOSPI_ROE':'코스피 ROE','KOSDAQ_ROE':'코스닥 ROE',
 'KOSPI_변동성':'코스피 실현변동성(20일 연율화)','KOSDAQ_변동성':'코스닥 실현변동성(20일 연율화)',
 '기준금리':'한국은행 기준금리','국고채3년':'국고채 3년','국고채10년':'국고채 10년',
 '회사채3년AA':'회사채 3년 AA−','CD91':'CD 91일','원달러':'원/달러 매매기준율',
 '신용스프레드':'회사채AA− − 국고채3년','선행지수':'경기선행지수 순환변동치',
 '수출금액':'통관 수출금액','수출금액지수':'수출금액지수','무역수지':'무역수지(순수출)',
 'VIX':'미국 변동성지수','US10Y':'미 국채 10년','US2Y':'미 국채 2년','T10Y2Y':'미 장단기금리차',
 'WTI':'WTI 유가','USD_BROAD':'달러 광범위 지수','HY_OAS':'미 하이일드 스프레드',
 'KRW_USD':'원/달러(FRED, 교차검증용)','예상PER':'코스피 12개월 선행 PER',
 '신용융자/예탁금':'신용융자 잔고 ÷ 투자자예탁금 (투자자 레버리지)',
 '고객예탁금(조원)':'투자자예탁금 잔고 (장내파생 예수금 제외)',
 '신용융자(조원)':'신용거래융자 잔고 (유가증권+코스닥)',
 '미수금(조원)':'위탁매매 미수금 (결제 못 한 외상 매수)',
 '반대매매비중(%)':'미수금 대비 실제 반대매매 체결 비중',
}
def data_section():
    rows = ''
    order = {'KRX 한국거래소':0, 'ECOS 한국은행':1, 'FRED 세인트루이스 연준':2,
             '금융투자협회 FreeSIS':3,
             '파생 (KRX 일별에서 산출)':4, '수동 입력 (애널리스트 컨센서스)':5}
    cols = [c for c in df.columns if c in COL_SRC]
    cols.sort(key=lambda c: (order.get(COL_SRC[c], 9), c))
    prev = None
    for c in cols:
        s = df[c].dropna()
        if not len(s): continue
        src = COL_SRC[c]
        if src != prev:
            rows += f'<tr class="grp"><td colspan="4">{src}</td></tr>'; prev = src
        used = ' <span class="used">모델 사용</span>' if c in USED_COLS else ''
        rows += (f'<tr><td>{c}{used}</td><td class="dsc">{DESC.get(c, "")}</td>'
                 f'<td>{s.index[0].strftime("%Y-%m")}~{s.index[-1].strftime("%Y-%m")}</td>'
                 f'<td>{len(s)}</td></tr>')
    files = ''.join(
        f'<div class="src"><div class="src-n">{lab}</div>'
        f'<div class="src-a">{api}</div>'
        f'<div class="src-t">최근 수집 {ts}<br><span class="src-f">{fn}</span></div></div>'
        for lab, api, fn, ts in FILE_INFO)
    return (f'<div class="sec"><div class="sec-head"><div class="sec-t">데이터 원천</div>'
            f'<div class="ctrls"><button class="btn" onclick="toggleD()">원천 보기/숨기기</button></div></div>'
            f'<div class="card" id="dWrap" style="display:none">'
            f'<div class="srcs">{files}</div>'
            f'<p class="note" style="margin:16px 0 12px">아래는 이 대시보드가 수집·보관하는 전체 시계열입니다. '
            f'<span class="used">모델 사용</span> 표시는 합성점수 산출에 직접 투입되는 지표이고, '
            f'나머지는 비교차트·원자료·파생 계산에 쓰입니다. 모든 z-score는 각 시점까지의 과거 구간만 사용합니다.</p>'
            f'<div class="rawscroll"><table class="raw dt"><thead><tr><th>계열</th><th>설명</th>'
            f'<th>기간</th><th>관측</th></tr></thead><tbody>{rows}</tbody></table></div></div></div>')

def glossary_section():
    rows = ''.join(f'<div class="gl"><div class="gl-t">{t}</div><div class="gl-d">{d}</div></div>'
                   for t, d in GLOSSARY)
    return (f'<div class="sec"><div class="sec-head"><div class="sec-t">용어 설명</div>'
            f'<div class="ctrls"><button class="btn" onclick="toggleG()">용어 보기/숨기기</button></div></div>'
            f'<div class="card" id="gWrap" style="display:none"><div class="glcols">{rows}</div></div></div>')

AK = analyze('KOSPI'); AQ = analyze('KOSDAQ')
asof = AK['asof']
if HAS_FPE:
    _lag = (asof.to_period('M') - FPE_ASOF.to_period('M')).n
    fpe_note = (f' · 예상PER {FPE_ASOF.strftime("%Y-%m")} 기준'
                + (f' <b style="color:#e08c3b">({_lag}개월 지연 — update_fwd_per.py 실행)</b>' if _lag >= 2 else ''))
    fpe_ph = f'{df["예상PER"].dropna().iloc[-1]:.1f}'
else:
    fpe_note = ' · <b style="color:#e08c3b">예상PER 없음</b>'
    fpe_ph = '예: 7.4'

# 순이익 입력칸 기본값 — 기존 입력 이력(fwd_ni.csv)이 있으면 그 값을 보여준다
_NI_Y1 = pd.Timestamp.today().year
_NI_Y2 = _NI_Y1 + 1
_ni_ph1, _ni_ph2 = '606', '946'
try:
    _nh = pd.read_csv(os.path.join(HERE, 'fwd_ni.csv'), index_col=0, parse_dates=True)
    _ni_ph1 = f"{float(_nh['FY1'].iloc[-1]):,.0f}"
    _ni_ph2 = f"{float(_nh['FY2'].iloc[-1]):,.0f}"
except Exception:
    pass
USED_COLS = set()
for _ix in ('KOSPI', 'KOSDAQ'):
    for _n, _s, *_r in signals_for(_ix):
        _nm = getattr(_s, 'name', None)
        if _nm in df.columns: USED_COLS.add(_nm)
for _c in ('KOSPI_PER', 'KOSDAQ_PER', '국고채10년', '수출금액', '예상PER',
           'WTI', 'US10Y', 'VIX', '기준금리',
           'KOSPI_종가', 'KOSDAQ_종가'):
    if _c in df.columns: USED_COLS.add(_c)
body = (section('코스피', AK) + section('코스닥', AQ) + weights_section(AK, AQ)
        + season_section(AK, AQ) + kelly_section(AK, AQ) + data_section() + glossary_section())

# ── 데이터 신선도 배지 ──
_DATA_ASOF = _d.dropna(how='all').index[-1]              # KRX 일별 마지막 거래일
# 달력일이 아니라 '거래일' 기준으로 센다(주말·공휴일에 빨간불이 뜨면 안 됨).
# KRX는 장 마감(15:30) 뒤 집계가 끝나야 당일치를 준다. 대체로 18시 이후.
_TODAY = pd.Timestamp.today()
_BDAYS = len(pd.bdate_range(_DATA_ASOF, _TODAY.normalize())) - 1
_TOO_EARLY = (_BDAYS == 1 and _TODAY.hour < 18)      # 오늘 데이터가 아직 안 나온 시간대
if _BDAYS <= 0 or _TOO_EARLY:
    _FRESH_CLS = 'ok'
    _FRESH_MSG = '최신' if _BDAYS <= 0 else '최신 (오늘치는 18시 이후 집계)'
elif _BDAYS <= 3:
    _FRESH_CLS, _FRESH_MSG = 'warn', f'{_BDAYS}거래일 지남'
else:
    _FRESH_CLS, _FRESH_MSG = 'bad', f'{_BDAYS}거래일 지남 — 갱신 필요'

# ── 비교차트 + 로우데이터용 데이터 ──
comp = {
    'KOSPI': df['KOSPI_종가'], 'KOSDAQ': df['KOSDAQ_종가'],
    'PER': df['KOSPI_PER'], 'PBR': df['KOSPI_PBR'], 'ROE': df['KOSPI_ROE'],
    '선행 PBR': (1.0 / (1.0 / df['KOSPI_PBR'].where(df['KOSPI_PBR'] > 0)
                        + (1.0 / df['예상PER'].where(df['예상PER'] > 0)) * 0.65)) if HAS_FPE else None,
    '순수출': df['무역수지'] if '무역수지' in df else df['수출금액'],
    '예상PER': df['예상PER'] if HAS_FPE else np.nan,
    '경기선행지수': df['선행지수'], '신용스프레드': df['신용스프레드'],
    '일드커브': df['국고채10년'] - df['국고채3년'],
    '일드갭': (100/df['예상PER'].where(df['예상PER'] > 0) - df['국고채10년']) if HAS_FPE
              else (100/df['KOSPI_PER'].where(df['KOSPI_PER'] > 0) - df['국고채10년']),
    '국고채10년': df['국고채10년'], '국고채3년': df['국고채3년'],
    '기준금리': df['기준금리'], '환율': df['원달러'], '실현변동성(20일)': df['KOSPI_변동성'], 'VKOSPI': df.get('VKOSPI'),
    'WTI 유가': df.get('WTI'), '미국10년': df.get('US10Y'),
    '미국10년 YoY': df['US10Y'].diff(12) if 'US10Y' in df else None,
    'VIX 급등(YoY)': df['VIX'].pct_change(12) * 100 if 'VIX' in df else None,
    '기준금리 YoY': df['기준금리'].diff(12),
    'VIX(미국)': df.get('VIX'), '달러지수': df.get('USD_BROAD'),
    '미국2년': df.get('US2Y'), '미국 장단기차': df.get('T10Y2Y'),
    '회사채AA-': df.get('회사채3년AA'), 'CD91': df.get('CD91'),
    '수출금액지수': df.get('수출금액지수'), '코스닥 변동성': df.get('KOSDAQ_변동성'),
    'M1': df.get('M1'), 'M2': df.get('M2'),
    'M2/M1 비율': (df['M2'] / df['M1']) if ('M2' in df and 'M1' in df) else None,
    'M2 증가율': df['M2'].pct_change(12, fill_method=None) * 100 if 'M2' in df else None,
    '시가총액/M2': (df['KOSPI_시총'] / df['M2'].ffill()) if ('M2' in df and 'KOSPI_시총' in df) else None,
    '신용융자/예탁금': df.get('신용융자/예탁금'),
    '고객예탁금(조원)': df.get('고객예탁금(조원)'), '신용융자(조원)': df.get('신용융자(조원)'),
    '미수금(조원)': df.get('미수금(조원)'), '반대매매비중(%)': df.get('반대매매비중(%)'),
    '코스피 종합점수': AK['sc'], '코스닥 종합점수': AQ['sc'],
}
comp = pd.DataFrame({k: v for k, v in comp.items() if v is not None}).loc['1995-01-31':]
DATA = {'dates': [d.strftime('%Y-%m') for d in comp.index],
        'series': {c: [None if pd.isna(v) else round(float(v), 3) for v in comp[c]]
                   for c in comp.columns},
        'ic': {AK['reads'][i][0]: {'ic': round(AK['ic'].get(_map, 0), 3),
                                   'w': round(AK['w'].get(_map, 0) * 100)}
               for i, _map in []},  # placeholder, filled below
        }
# IC·가중치 정보(코스피 기준)를 지표명→값으로 매핑해 차트에 표시
_SIG2COL2 = {'PBR': 'PBR', 'PER': 'PER', 'ROE': 'ROE', '실현변동성(20일)': '실현변동성(20일)', 'VKOSPI': 'VKOSPI',
             # 선행 PBR이 빠져 있었다. 그 탓에 차트가 방향 정보를 못 받아 기본값(위=유리)으로
             # 칠했는데, 선행 PBR은 '낮을수록 강세'라 유불리가 정반대로 표시되고 있었다.
             '선행 PBR': '선행 PBR',
             '환율(원/달러)': '환율', '경기선행지수': '경기선행지수', '신용스프레드': '신용스프레드',
             '일드커브': '일드커브', '국고채10년': '국고채10년',
             'WTI 유가': 'WTI 유가', '미국10년 YoY': '미국10년 YoY',
             'VIX 급등(YoY)': 'VIX 급등(YoY)', '기준금리 YoY': '기준금리 YoY',
             '기준금리': '기준금리',
             '수출 YoY': '순수출', '예상PER 괴리': '예상PER',
             '시가총액/M2': '시가총액/M2', 'M2 증가율(YoY)': 'M2 증가율', 'M2/M1 비율': 'M2/M1 비율',
             '신용융자/예탁금': '신용융자/예탁금',
             '일드갭 (예상PER)': '일드갭', '일드갭 (후행PER)': '일드갭'}
DATA['ic'] = {}
for _n in AK['ic']:
    _col = _SIG2COL2.get(_n)
    if _col:
        DATA['ic'][_col] = {'ic': round(AK['ic'][_n], 3), 'w': round(AK['w'][_n] * 100),
                            'dir': ('낮을수록 강세' if AK['direction'][_n][0] < 0 else '높을수록 강세')
                                   + (' · 역발상' if AK['direction'][_n][1] else '')}
# 구조 단절이 있어 일부 구간을 신호에서 제외한 지표: 차트에 절단선과 사유를 표시한다.
#   (유불리 중앙값도 절단 이후 구간에서만 계산해야 차트와 신호 분해가 어긋나지 않는다)
if HAS_CREDIT and '신용융자/예탁금' in DATA['ic']:
    DATA['ic']['신용융자/예탁금']['from'] = CREDIT_FROM.strftime('%Y-%m')
    DATA['ic']['신용융자/예탁금']['fromWhy'] = (
        '2007년 신용공여 제도 급성장 (신용융자 2006년 0.47조 → 2007년 4.40조, 9.4배). '
        '이전 구간은 사실상 다른 시장이라 신호 계산에서 제외 — 차트에는 맥락으로 남김.')
DATA['scoremeta'] = {'method': '각 지표를 강세방향 z-score로 변환 → 예측력(IC) 기반 Ridge 다변량 가중합. 양수=유리, 음수=불리.'}
# 드롭다운 순서 = 신호 분해의 번호 순서(가중치 큰 순)와 일치시킴
SIG2COL = {'PBR': 'PBR', 'PER': 'PER', 'ROE': 'ROE', '실현변동성(20일)': '실현변동성(20일)', 'VKOSPI': 'VKOSPI',
           '선행 PBR': '선행 PBR',
           '환율(원/달러)': '환율', '경기선행지수': '경기선행지수', '신용스프레드': '신용스프레드',
           '일드커브': '일드커브', '국고채10년': '국고채10년',
           'WTI 유가': 'WTI 유가', '미국10년 YoY': '미국10년 YoY',
           'VIX 급등(YoY)': 'VIX 급등(YoY)', '기준금리 YoY': '기준금리 YoY',
           '기준금리': '기준금리',
           '수출 YoY': '순수출', '예상PER 괴리': '예상PER',
             '시가총액/M2': '시가총액/M2', 'M2 증가율(YoY)': 'M2 증가율', 'M2/M1 비율': 'M2/M1 비율',
           '신용융자/예탁금': '신용융자/예탁금',
           '일드갭 (예상PER)': '일드갭', '일드갭 (후행PER)': '일드갭'}
_ordered, _seen = [('▸ 코스피 종합점수', '코스피 종합점수'), ('▸ 코스닥 종합점수', '코스닥 종합점수')], {'코스피 종합점수', '코스닥 종합점수'}
for _i, _r in enumerate(AK['reads'], 1):          # 코스피 신호분해 순서 그대로
    _c = SIG2COL.get(_r[0])
    if _c and _c in comp.columns and _c not in _seen:
        _ordered.append((f'{_i}. {_c}', _c)); _seen.add(_c)
for _c in comp.columns:                            # 신호에 없는 참고 지표는 뒤에
    if _c not in _seen and _c not in ('KOSPI', 'KOSDAQ'):
        _ordered.append((f'· {_c}', _c)); _seen.add(_c)
opts = ''.join(f'<option value="{v}">{lab}</option>' for lab, v in _ordered)
data_json = json.dumps(DATA, ensure_ascii=False)

compare_html = f'''<div class="sec"><div class="sec-head"><div class="sec-t">지표 비교</div>
  <div class="ctrls">
    <select id="baseSel"><option value="KOSPI">코스피 기준</option><option value="KOSDAQ">코스닥 기준</option></select>
    <select id="indSel">{opts}</select>
  </div></div>
  <div class="card"><div id="chartWrap"><div id="chart"></div><div id="ctip" class="ctip"></div></div>
    <div class="chart-lgd"><span><i style="background:#4a9fd4"></i><span id="lgdBase">코스피</span><span class="lgd-log">로그</span></span>
      <span><i style="background:#e0913b"></i><span id="lgdInd">PER</span></span></div>
    <div id="indInfo" class="indinfo"></div>
  </div></div>
<div class="sec"><div class="sec-head"><div class="sec-t">원자료 (Raw data)</div>
  <div class="ctrls"><button class="btn" onclick="toggleRaw()">원자료 보기/숨기기</button>
    <button class="btn" onclick="downloadCSV()">CSV 다운로드</button></div></div>
  <div class="card" id="rawWrap" style="display:none"><div id="rawTable" class="rawscroll"></div></div></div>'''

html_doc = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>코스피·코스닥 국면 대시보드</title>
<style>
:root{{--bg:#0e1420;--panel:#161d2b;--panel2:#1b2333;--line:#26324a;--tx:#e6edf3;--mut:#8b98ab;
  --mono:ui-monospace,"SF Mono","Cascadia Code",Consolas,monospace;}}
*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#182236 0%,var(--bg) 55%);
  color:var(--tx);font-family:system-ui,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1060px;margin:0 auto;padding:30px 22px 60px}}
.top{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid var(--line);
  padding-bottom:14px;margin-bottom:24px}}
.top .t{{font-size:20px;font-weight:650}}.top .t small{{display:block;color:var(--mut);font-weight:400;font-size:12.5px;margin-top:3px}}
.sec{{margin-bottom:30px}}
.sec-head{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:8px}}
.sec-t{{font-size:22px;font-weight:700}}
.sec-px{{font-family:var(--mono);font-size:15px;color:var(--mut);margin-left:8px}}
.sec-score{{text-align:right;display:flex;align-items:baseline;gap:10px;
  background:rgba(15,22,35,.55);border-radius:10px;padding:4px 12px;backdrop-filter:blur(1px)}}
.ss{{font-family:var(--mono);font-size:30px;font-weight:600}}
.sr{{font-size:18px;font-weight:700}}
.sp{{font-family:var(--mono);font-size:11.5px;color:var(--mut)}}
.strip{{margin-bottom:14px}}
.projbox{{background:#131b2a;border:1px solid var(--line);border-radius:10px;padding:12px 15px;margin-bottom:12px}}
.proj-h{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:13px;margin-bottom:6px}}
.proj-h b{{font-family:var(--mono);font-size:15px}}
.proj-p{{color:var(--mut);font-size:11px}}
.proj-sel{{background:#0f1626;color:#b9c4d4;border:1px solid var(--line);border-radius:5px;font-size:11px;padding:1px 4px;font-family:var(--mono);cursor:pointer;margin-left:4px}}
.proj-med{{color:#b9c4d4;font-family:var(--mono);font-size:12px}}
.proj-cap{{font-size:10.5px;color:#8b98ab;margin-top:5px;line-height:1.5}}
.expbar{{display:flex;align-items:baseline;gap:14px;background:#131b2a;border:1px solid var(--line);
  border-radius:10px;padding:9px 14px;margin-bottom:12px;flex-wrap:wrap}}
.exp-lab{{font-size:11.5px;color:var(--mut)}}
.exp-m{{font-family:var(--mono);font-size:19px;font-weight:600}}
.exp-w{{font-family:var(--mono);font-size:13px;color:var(--tx)}}
.exp-n{{font-size:10.5px;color:#5b6678;margin-left:auto}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:16px}}
.card h2{{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--mut);margin:0 0 14px;font-weight:600}}
.h2-sub{{text-transform:none;letter-spacing:0;color:#5b6678;font-size:10.5px;font-weight:400;margin-left:6px}}
/* ── 콤팩트 신호 목록: 한 줄에 하나 ── */
.siglist{{display:flex;flex-direction:column;gap:3px}}
.sg{{display:flex;align-items:center;gap:8px;padding:5px 9px;background:#121a28;border:1px solid #202b3e;
  border-radius:7px;font-size:12.5px}}
.sg:has(.sigck:not(:checked)){{opacity:.38}}
.sg-ck{{display:inline-flex;align-items:center;cursor:pointer;flex:none}}
.sg-ck input{{width:14px;height:14px;accent-color:#4a9fd4;cursor:pointer;margin:0}}
.sg-i{{flex:none;width:17px;height:17px;display:inline-flex;align-items:center;justify-content:center;
  background:#1e293c;border-radius:4px;font-family:var(--mono);font-size:10px;color:#8b98ab}}
.sg-n{{font-weight:600;min-width:104px;flex:none}}
.sg-bar{{position:relative;flex:1;min-width:48px;height:6px;background:#0b1220;border:1px solid #1c2637;
  border-radius:4px;overflow:hidden}}
.sg-bar .sg-mid{{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#3a465a}}
.sg-bar .sg-fill{{position:absolute;top:0;bottom:0;border-radius:4px}}
.sg-val{{font-family:var(--mono);font-size:11.5px;font-weight:600;width:46px;text-align:right;flex:none}}
.sg-rv{{font-family:var(--mono);font-size:11px;color:#8b98ab;width:64px;text-align:right;flex:none;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sg-w{{font-family:var(--mono);font-size:11px;color:var(--mut);width:34px;text-align:right;flex:none}}
.na{{color:#5b6678;font-size:11px}}
@media(max-width:760px){{.sg-rv{{display:none}}.sg-n{{min-width:82px}}}}
.lad-r{{display:flex;align-items:center;gap:10px}}
.lad-ex{{font-size:10.5px;color:#8b98ab;padding:3px 0 1px 62px;line-height:1.5}}
.lad-ex b{{color:#b9c4d4;font-family:var(--mono);font-weight:600}}
.topbtns{{display:flex;gap:9px;align-items:center;flex-wrap:wrap}}
.dbadge{{display:flex;align-items:center;gap:5px;font-size:11.5px;border-radius:8px;
  padding:6px 10px;border:1px solid;font-family:var(--mono)}}
.dbadge b{{font-family:inherit;font-weight:600}}
.dbadge.ok{{color:#3fb37f;border-color:#1e4d3a;background:#0d1f18}}
.dbadge.warn{{color:#e8a33d;border-color:#5a4520;background:#211a0d}}
.dbadge.bad{{color:#e5484d;border-color:#5a2326;background:#210f10}}
.fpe-in{{display:flex;align-items:center;gap:6px;background:#101725;border:1px solid var(--line);
  border-radius:8px;padding:5px 10px}}
.fpe-in label{{font-size:11.5px;color:var(--mut)}}

.fpe-unit{{font-size:10.5px;color:#8b98ab;margin-left:2px;margin-right:4px}}
.fpe-sep{{font-size:10px;color:#5b6678;margin-right:3px}}
.fpe-alt{{opacity:.7}}
.fpe-in input{{background:transparent;border:none;outline:none;color:var(--tx);
  font-family:var(--mono);font-size:13px;width:52px;text-align:right}}
.btn.upd{{background:#1b3a5c;border-color:#2b5480;color:#dce9f7;font-weight:600;padding:8px 15px}}
.btn.upd:hover{{background:#22486f;border-color:#3a6da3}}
.btn.upd:disabled{{opacity:.55;cursor:default}}
.updpanel{{display:none;margin:0 0 20px;background:#0b1220;border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.updpanel.on{{display:block}}
.updlog{{font-family:var(--mono);font-size:11.5px;color:#a8b3c4;white-space:pre-wrap;
  max-height:260px;overflow:auto;line-height:1.6}}
.updlog .ok{{color:#3fb37f}}.updlog .err{{color:#e5484d}}.updlog .hi{{color:#e6edf3}}
/* ── 계절 오버레이 ── */
.seabar{{display:flex;gap:26px;flex-wrap:wrap;padding:2px 0 14px;margin-bottom:14px;
  border-bottom:1px solid var(--line)}}
.seabar .k{{display:block;font-size:10.5px;color:var(--mut);margin-bottom:3px}}
.seabar .v{{font-family:var(--mono);font-size:15px;font-weight:600}}
.seabar .v small{{font-size:11px;color:var(--mut);font-weight:400}}
.seabar .v.ok{{color:#3fb37f}}.seabar .v.bad{{color:#e5484d}}
.seacols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:700px){{.seacols{{grid-template-columns:1fr}}}}
.seac{{background:#101725;border:1px solid var(--line);border-radius:11px;padding:14px 15px}}
.seac-h{{font-size:14px;font-weight:700;margin-bottom:8px}}
.seaspark{{width:100%;height:52px;display:block;margin-bottom:11px}}
.seagrid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 14px}}
.seagrid .k{{display:block;font-size:10.5px;color:var(--mut);margin-bottom:2px}}
.seagrid .v{{display:block;font-family:var(--mono);font-size:18px;font-weight:650;line-height:1.15}}
.seagrid .v small{{font-size:10.5px;color:var(--mut);font-weight:400;margin-left:1px}}
.seagrid .c{{display:block;font-size:10px;color:#5b6678;margin-top:3px;line-height:1.45}}
.seabw{{font-size:10.5px;color:#5b6678;margin-top:11px}}
.seabw b{{color:#b9c4d4;font-family:var(--mono)}}
.skrow{{display:flex;align-items:center;gap:11px;margin-top:11px;padding:9px 11px;
  background:#0d1424;border:1px solid #22304a;border-radius:9px}}
.sk-l{{font-size:11px;color:var(--mut);flex:none;max-width:96px;line-height:1.45}}
.sk-v{{font-family:var(--mono);font-size:23px;font-weight:650;flex:none}}
.sk-d{{font-size:10.5px;color:#b9c4d4;font-family:var(--mono);line-height:1.55;margin-left:auto;text-align:right}}
.slink{{color:#6cb6e8}}
.kcols{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:16px 0}}
@media(max-width:700px){{.kcols{{grid-template-columns:1fr}}}}
.kb{{background:#101725;border:1px solid var(--line);border-radius:11px;padding:15px 16px}}
.kb-h{{font-size:14px;font-weight:700;margin-bottom:8px}}
.kb-big{{font-family:var(--mono);font-size:38px;font-weight:600;line-height:1}}
.kb-cap{{font-size:11.5px;color:var(--mut);margin:4px 0 3px}}
.kb-warn{{background:#2a1f14;border:1px solid #5a3f1f;border-radius:7px;padding:6px 9px;font-size:10.5px;color:#e0b080;margin:6px 0 8px}}
.kt .grp{{background:#131b2b;font-size:10.5px;color:#8b98ab}}
.kt .bd{{border-right:1px solid #2b3648}}
.kb-note{{font-size:10px;color:#5b6678;margin-top:6px}}
.kb-sub{{font-size:11px;color:#8b98ab;font-family:var(--mono);margin-bottom:11px;line-height:1.6}}
table.kt{{font-size:11px}}
table.kt td:first-child,table.kt th:first-child{{text-align:left}}
table.kt td.dim{{color:#6b7a90}}
table.kt tr.here td{{background:#101d2a}}
table.kt tr.here td:first-child{{color:var(--tx);font-weight:600}}
.bt-h{{font-size:13.5px;font-weight:700;margin:20px 0 8px;padding-top:16px;border-top:1px solid var(--line)}}
table.bt tr.best td{{background:#101d2a}}
table.bt tr.best td:first-child{{color:#3fb37f;font-weight:600}}
.kwarn{{background:#1c1418;border:1px solid #4a2530;border-radius:9px;padding:12px 14px;
  color:#d8b4bc !important;font-size:11.5px}}
.kwarn b{{color:#f0c4cc}}
.srcs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.src{{background:#101725;border:1px solid var(--line);border-radius:10px;padding:11px 13px}}
.src-n{{font-size:13px;font-weight:600;margin-bottom:3px}}
.src-a{{font-size:11px;color:#8b98ab;font-family:var(--mono);word-break:break-all}}
.src-t{{font-size:11px;color:var(--mut);margin-top:7px;font-family:var(--mono);line-height:1.6}}
.src-f{{color:#5b6678;font-size:10px}}
table.dt td:first-child,table.dt th:first-child{{text-align:left;font-family:var(--mono)}}
table.dt td.dsc{{text-align:left;color:#a8b3c4;font-family:inherit;font-size:11.5px}}
table.dt tr.grp td{{background:#131b2a;color:#8b98ab;font-weight:600;text-align:left;
  font-size:11.5px;letter-spacing:.03em;padding:7px 8px}}
.used{{display:inline-block;background:#14342a;border:1px solid #2b5b45;color:#3fb37f;
  font-size:9.5px;padding:1px 5px;border-radius:4px;margin-left:5px;font-family:inherit}}
.credit{{margin-top:10px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
  font-size:11.5px;color:var(--mut)}}
.credit b{{color:var(--tx);font-weight:600}}
.credit a{{color:#4a9fd4;text-decoration:none}}.credit a:hover{{text-decoration:underline}}
.glcols{{display:grid;grid-template-columns:1fr 1fr;gap:14px 22px}}
@media(max-width:700px){{.glcols{{grid-template-columns:1fr}}}}
.gl{{padding-bottom:11px;border-bottom:1px solid #1e2838}}
.gl-t{{font-size:13.5px;font-weight:600;margin-bottom:3px}}
.gl-d{{font-size:12px;color:#a8b3c4;line-height:1.65}}.gl-d b{{color:var(--tx)}}
.headline{{text-align:center;padding:4px 0 12px;border-bottom:1px dashed var(--line);margin-bottom:12px}}
.headline .big{{font-family:var(--mono);font-size:38px;font-weight:600}}
.headline .cap{{color:var(--mut);font-size:12px;margin-top:2px}}
.mh-row{{display:flex;gap:9px;margin-bottom:16px}}
.mh{{flex:1;background:#101725;border:1px solid var(--line);border-radius:9px;padding:8px 5px;text-align:center}}
.mh-h{{display:block;color:var(--mut);font-size:11px}}
.mh-m{{display:block;font-family:var(--mono);font-size:18px;font-weight:600;margin:2px 0}}
.mh-w{{display:block;color:var(--mut);font-size:10.5px;font-family:var(--mono)}}
.lad{{display:flex;align-items:center;gap:10px;padding:6px 10px;border-radius:8px;margin-bottom:4px}}
.lad-b{{width:52px;font-size:12px;color:var(--mut)}}
.lad-m{{font-family:var(--mono);font-size:15px;font-weight:600;width:56px}}
.lad-w{{font-family:var(--mono);font-size:11.5px;color:var(--mut)}}
.lad.here{{background:#101d2a;border:1px solid #2b5b45}}.lad.here .lad-b{{color:var(--tx);font-weight:600}}
.lad-tag{{margin-left:auto;font-size:10.5px;color:#3fb37f;font-family:var(--mono)}}
.ctrls{{display:flex;gap:8px}}
select,.btn{{background:#101725;color:var(--tx);border:1px solid var(--line);border-radius:8px;
  padding:6px 11px;font-size:12.5px;font-family:inherit;cursor:pointer}}
select:hover,.btn:hover{{border-color:#3a4a63}}
#chartWrap{{position:relative;width:100%}}
#chart{{width:100%}}#chart svg{{width:100%;height:auto;display:block}}
#chit{{cursor:crosshair}}
.ctip{{display:none;position:absolute;pointer-events:none;background:rgba(11,18,32,.72);
  backdrop-filter:blur(2px);border:1px solid rgba(43,54,72,.7);
  border-radius:8px;padding:8px 11px;font-size:11.5px;font-family:var(--mono);color:var(--tx);
  box-shadow:0 4px 14px rgba(0,0,0,.3);z-index:5;white-space:nowrap}}
.ctip .tp-d{{color:var(--mut);font-size:10.5px;margin-bottom:5px}}
.ctip .tp-r{{display:flex;align-items:center;gap:6px;line-height:1.75}}
.ctip .tp-r i{{width:9px;height:3px;border-radius:2px;display:inline-block}}
.ctip .tp-r b{{margin-left:auto;padding-left:14px;font-weight:600}}
.indinfo{{margin-top:10px;padding:9px 12px;background:#101725;border:1px solid var(--line);border-radius:8px;font-size:12px;color:#b9c4d4;font-family:var(--mono)}}
.indinfo b{{color:var(--tx)}}
.ii-note{{color:var(--mut);font-size:10.5px}}
.lgd-log{{font-size:9.5px;color:#5b6678;border:1px solid #2b3648;border-radius:4px;padding:1px 4px;margin-left:5px}}
.chart-lgd{{display:flex;gap:20px;justify-content:center;margin-top:8px;font-size:12px;color:var(--mut)}}
.chart-lgd i{{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}}
.rawscroll{{max-height:420px;overflow:auto}}
.note{{font-size:12.5px;color:#b9c4d4;line-height:1.7;margin:0 0 16px}}.note b{{color:var(--tx)}}
.wcols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
@media(max-width:640px){{.wcols{{grid-template-columns:1fr}}}}
.wcols h3{{font-size:14px;margin:0 0 8px;color:var(--tx)}}
table.wt{{font-size:12px}}table.wt td:first-child,table.wt th:first-child{{text-align:left}}
table.wt td:nth-child(2),table.wt th:nth-child(2),table.wt td:nth-child(4),table.wt th:nth-child(4){{text-align:right}}
.wbar{{width:70px;height:7px;background:#101725;border-radius:4px;overflow:hidden;display:inline-block;vertical-align:middle}}
.wbar span{{display:block;height:100%;background:#4a9fd4;border-radius:4px}}
table.wt td.dir{{text-align:left;color:#8b98ab;font-size:11px}}
.con{{color:#e0913b}}
table.raw{{border-collapse:collapse;width:100%;font-family:var(--mono);font-size:11px}}
table.raw th,table.raw td{{padding:4px 8px;text-align:right;white-space:nowrap;border-bottom:1px solid #1e2838}}
table.raw th{{position:sticky;top:0;background:#131b2a;color:var(--mut);font-weight:600;text-align:right}}
table.raw td:first-child,table.raw th:first-child{{text-align:left;color:var(--mut);position:sticky;left:0;background:var(--panel)}}
footer{{margin-top:8px;color:#5b6678;font-size:11.5px;line-height:1.6;border-top:1px solid var(--line);padding-top:14px}}
</style></head><body><div class="wrap">
<div class="top"><div class="t">코스피 · 코스닥 국면 대시보드
  <small>WeightSum 밸류에이션·매크로 합성 · 지수별 독립 산출 · 기준 {asof.date()}{fpe_note}</small></div>
  <div class="topbtns">
    <span class="dbadge {_FRESH_CLS}" title="대시보드에 박혀 있는 데이터의 마지막 거래일입니다. 파일을 새로 열어도 이 값은 바뀌지 않고, 데이터 최신화를 눌러야 갱신됩니다.">
      <b>데이터</b> {_DATA_ASOF:%Y-%m-%d} · {_FRESH_MSG}
    </span>
    <span class="fpe-in" title="증권사·FnGuide 컨센서스 순이익(조원). 비워두면 기존값 유지">
      <label>예상순이익</label>
      <span class="fpe-sep">{_NI_Y1}</span>
      <input id="niY1" type="text" inputmode="decimal" value="{_ni_ph1}" size="5"
             title="{_NI_Y1}년(올해) 예상 순이익, 단위 조원">
      <span class="fpe-unit">조</span>
      <span class="fpe-sep">{_NI_Y2}</span>
      <input id="niY2" type="text" inputmode="decimal" value="{_ni_ph2}" size="5"
             title="{_NI_Y2}년(내년) 예상 순이익, 단위 조원">
      <span class="fpe-unit">조</span>
    </span>
    <span class="fpe-in fpe-alt" title="PER을 직접 넣고 싶을 때만. 비워두면 무시">
      <label for="fpeVal">또는 PER</label>
      <input id="fpeVal" type="text" inputmode="decimal" placeholder="{fpe_ph}" size="4">
    </span>
    <button class="btn upd" id="updBtn" onclick="doUpdate()">
    <span id="updTxt">데이터 최신화</span></button></div></div>
<div id="updPanel" class="updpanel"><div id="updLog" class="updlog"></div></div>
{compare_html}
{body}
<footer>각 지수는 자기 PBR·일드갭·변동성과 공통 매크로(환율·경기선행지수·신용스프레드)를, 그 지수의 과거
 예측력(해당 지수 12개월 IC)에 비례해 가중합합니다. 예상PER은 코스피 전용(차트 복원 근사치). 모든 z-score는
 과거 구간만 사용(미래참조 없음). 기대수익은 2005년 이후 실현치·중첩표본이라 신뢰구간이 넓고 레짐 의존적입니다.
 <b>과거 통계 기반 국면 진단이며 투자 조언이 아닙니다.</b>
  <div class="credit">
    <span>개발자 <b>워렌결핍</b> · <a href="mailto:yunmaerae@gmail.com">yunmaerae@gmail.com</a></span>
    <span>데이터 출처: KRX · 한국은행 ECOS · FRED</span>
  </div></footer>
</div>
<script>
const DATA = {data_json};
const D = DATA.dates, S = DATA.series;

// ── 체크박스로 신호를 뺐다 넣었다 하며 종합점수를 즉시 재계산 ──
//   종합점수 = Σ(z × 가중치). 체크 해제된 신호는 빼고 남은 가중치를 재정규화.
//   백분위·국면 라벨도 과거 점수분포(SCDIST)에 다시 대입해 갱신한다.
function _regimeLabel(pct){{
  if(pct>=0.80) return ['매우 유리','#3fb37f'];
  if(pct>=0.60) return ['유리','#5fb37f'];
  if(pct>=0.40) return ['중립','#b0b8c4'];
  if(pct>=0.20) return ['불리','#e0913b'];
  return ['매우 불리','#e5484d'];
}}
function recalc(idx){{
  const boxes=[...document.querySelectorAll('.sigck[data-idx="'+idx+'"]')];
  let score=0, wsum=0, wtot=0, allOn=true;
  boxes.forEach(b=>{{
    const w=parseFloat(b.dataset.w)||0, z=b.dataset.z===''?null:parseFloat(b.dataset.z);
    if(z===null) return;
    if(w<=0) return;              // 참고지표(가중 0)는 점수에 영향 없음 — 정규화에서도 제외
    wtot+=w;
    if(b.checked){{ score+=z*w; wsum+=w; }}
    else allOn=false;            // 하나라도 꺼져 있으면 재계산
  }});
  // [중요] 전부 켜져 있으면 재계산의 부동소수점 오차로 원래 점수가 살짝 달라져
  //   구간(bin)이 튀는 문제가 있다. 이 경우엔 원본 기준값(SCBASE)을 그대로 써서
  //   '해제 → 재체크' 시 완벽히 복구되게 한다.
  const base=(window.SCBASE&&window.SCBASE[idx]);
  if(allOn && base!=null){{
    score=base;
  }} else if(wsum>0){{
    score=score*(wtot/wsum);
  }} else {{
    score=(base!=null)?base:0;   // 전부 꺼지면 기준값
  }}
  const dist=(window.SCDIST&&window.SCDIST[idx])||[];
  let pct=0.5;
  if(dist.length){{ pct=dist.filter(v=>v<score).length/dist.length; }}
  const [lab,col]=_regimeLabel(pct);
  const ss=document.getElementById('ss-'+idx), sr=document.getElementById('sr-'+idx), sp=document.getElementById('sp-'+idx);
  if(ss){{ ss.textContent=(score>=0?'+':'')+score.toFixed(2); ss.style.color=col; }}
  if(sr){{ sr.textContent=lab; sr.style.color=col; }}
  if(sp){{
    const base=(window.SCBASE&&window.SCBASE[idx]);
    const diff=(base!=null)?(score-base):0;
    sp.textContent='백분위 '+Math.round(pct*100)+'%'+(Math.abs(diff)>0.001?'  (기본 대비 '+(diff>=0?'+':'')+diff.toFixed(2)+')':'');
  }}
  // ── 새 점수가 어느 구간인지 찾아 '기대수익'도 갱신 ──
  //   [중요] 구간(bin)은 점수의 '백분위 순위 × NB'로 정한다(_bins와 동일 방식).
  //   과거엔 qedges(2~4개 경계)로 bin을 찾았는데, 사다리가 7단계로 바뀌며 경계 수가
  //   안 맞아, 체크 해제 시 bin이 엉뚱하게(예: 최유리인데 중간) 튀어 예측이 -1%로
  //   무너지는 버그가 있었다. SCDIST(과거 점수분포)로 백분위를 구해 NB등분한다.
  const NB=(window.BINRET&&window.BINRET[idx])?Object.keys(window.BINRET[idx]).length:7;
  let bin;
  if(allOn && window.CBIN && window.CBIN[idx]!=null){{
    bin=window.CBIN[idx];
  }} else {{
    // 점수 백분위(pct) → 구간. dist 대비 순위로 계산해 _bins와 일치시킴.
    const p=dist.length?dist.filter(v=>v<score).length/dist.length:0.5;
    bin=Math.min(Math.floor(p*NB), NB-1);
  }}
  const ret=(window.BINRET&&window.BINRET[idx])||{{}};
  const mh=(window.BINMH&&window.BINMH[idx])||{{}};
  const pf=v=>(v>=0?'+':'')+Math.round(v*100)+'%';
  if(ret[bin]){{
    const [m12,w12]=ret[bin], c=m12>=0?'#3fb37f':'#e5484d';
    const big=document.getElementById('fbig-'+idx);
    if(big){{ big.textContent=pf(m12); big.style.color=c; }}
    const cap=document.getElementById('fcap-'+idx);
    if(cap) cap.textContent='상승확률 '+Math.round(w12*100)+'%';
    const em=document.getElementById('em-'+idx);
    if(em){{ em.textContent='평균 '+pf(m12); em.style.color=c; }}
    const ew=document.getElementById('ew-'+idx);
    if(ew) ew.textContent='상승확률 '+Math.round(w12*100)+'%';
  }}
  // 기간별(3/6/12개월) 갱신
  if(mh[bin]){{
    [3,6,12].forEach(h=>{{
      const v=mh[bin][h]; if(!v) return;
      const mm=document.getElementById('mhm-'+idx+'-'+h), mw=document.getElementById('mhw-'+idx+'-'+h);
      if(mm){{ mm.textContent=pf(v[0]); mm.style.color=v[0]>=0?'#3fb37f':'#e5484d'; }}
      if(mw) mw.textContent='승률 '+Math.round(v[1]*100)+'%';
    }});
  }}
  // 사다리(구간표)에서 '지금 여기' 위치 이동
  for(let b=0;b<NB;b++){{
    const row=document.getElementById('lad-'+idx+'-'+b);
    const tw=document.getElementById('ladtag-'+idx+'-'+b);
    if(!row) continue;
    if(b===bin){{ row.classList.add('here'); if(tw) tw.innerHTML='<span class="lad-tag">지금 여기</span>'; }}
    else{{ row.classList.remove('here'); if(tw) tw.innerHTML=''; }}
  }}
  // ── 12개월 뒤 지수 예측 박스도 갱신 (텍스트 + 히스토그램 차트 전부) ──
  window.__CURBIN=window.__CURBIN||{{}}; window.__CURBIN[idx]=bin;
  updateProjChart(idx, bin);
  const sc2=document.getElementById('pjscore-'+idx);
  if(sc2){{ const lab2=_regimeLabel((dist.length?dist.filter(v=>v<score).length/dist.length:0.5))[0];
    sc2.textContent=(score>=0?'+':'')+score.toFixed(2)+'('+lab2+')'; }}
}}

// 예측 박스(범위텍스트·중앙·상승확률·히스토그램 밴드/중앙선/라벨)를 국면·구간%에 맞게 다시 그림
function updateProjChart(idx, bin){{
  const pjb=(window.PJBIN&&window.PJBIN[idx])||{{}};
  const v=pjb[bin]; if(!v) return;
  const sel=document.getElementById('pjsel-'+idx);
  const p=sel?sel.value:'50';
  const bd=(v.bands&&v.bands[p])||v.bands['50'];
  const fmt=n=>Math.round(n).toLocaleString();
  // 상단 텍스트
  const rng=document.getElementById('pjrange-'+idx);
  if(rng&&bd) rng.textContent=fmt(bd[0])+' ~ '+fmt(bd[1]);
  const md=document.getElementById('pjmed-'+idx);
  if(md) md.textContent='중앙 '+fmt(v.med)+' · 상승확률 '+Math.round(v.up*100)+'%';
  // 히스토그램 밴드/중앙선/라벨 좌표 갱신
  const ax=(window.PJAX&&window.PJAX[idx]); if(!ax||!bd) return;
  const X=val=>8+(val-ax.lo)/(ax.hi-ax.lo)*(ax.W-16);
  const band=document.getElementById('pjband-'+idx);
  if(band){{ band.setAttribute('x',X(bd[0]).toFixed(1)); band.setAttribute('width',(X(bd[1])-X(bd[0])).toFixed(1)); }}
  const ml=document.getElementById('pjmedln-'+idx);
  if(ml){{ ml.setAttribute('x1',X(v.med).toFixed(1)); ml.setAttribute('x2',X(v.med).toFixed(1)); }}
  const lo_=document.getElementById('pjlo-'+idx);
  if(lo_){{ lo_.setAttribute('x',X(bd[0]).toFixed(1)); lo_.textContent=fmt(bd[0]); }}
  const hi_=document.getElementById('pjhi-'+idx);
  if(hi_){{ hi_.setAttribute('x',X(bd[1]).toFixed(1)); hi_.textContent=fmt(bd[1]); }}
  const mlab=document.getElementById('pjmedlab-'+idx);
  if(mlab){{ mlab.setAttribute('x',X(v.med).toFixed(1)); mlab.textContent='중앙 '+fmt(v.med); }}
}}

// 신뢰구간(%) 선택 변경 시 — 현재 국면(bin) 기준으로 전체 다시 그림
function setBand(idx){{
  const bin=(window.__CURBIN&&window.__CURBIN[idx]!=null)?window.__CURBIN[idx]:(window.CBIN&&window.CBIN[idx]);
  updateProjChart(idx, bin);
}}

function niceMinMax(a){{let v=a.filter(x=>x!=null);let mn=Math.min(...v),mx=Math.max(...v);
  let pad=(mx-mn)*0.08||1;return [mn-pad,mx+pad];}}
function draw(){{
  const baseK=document.getElementById('baseSel').value, indK=document.getElementById('indSel').value;
  const base=S[baseK], ind=S[indK];
  const W=980,H=360,mL=64,mR=64,mT=16,mB=28;
  const [b0r,b1r]=niceMinMax(base),[i0,i1]=niceMinMax(ind);
  const n=D.length;
  const X=i=>mL+i/(n-1)*(W-mL-mR);
  // 지수(코스피/코스닥) 축은 로그 스케일 — 20년 구간에서 같은 % 변동이 같은 높이로 보이도록
  const bPos=base.filter(v=>v!=null&&v>0);
  const LOGB=bPos.length>0;
  const b0=LOGB?Math.min.apply(null,bPos)*0.97:b0r;
  const b1=LOGB?Math.max.apply(null,bPos)*1.03:b1r;
  const lb0=LOGB?Math.log10(b0):0, lb1=LOGB?Math.log10(b1):1;
  const Yb=v=>LOGB
    ? (v>0 ? H-mB-(Math.log10(v)-lb0)/(lb1-lb0)*(H-mT-mB) : H-mB)
    : H-mB-(v-b0r)/(b1r-b0r)*(H-mT-mB);
  const Yi=v=>H-mB-(v-i0)/(i1-i0)*(H-mT-mB);
  function path(arr,Y){{let d='',pen=false;for(let i=0;i<n;i++){{const v=arr[i];
    if(v==null){{pen=false;continue;}} d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)+' ';pen=true;}}return d;}}
  let grid='',ax='';
  for(let g=0;g<=4;g++){{const y=mT+g/4*(H-mT-mB);
    const bv=LOGB?Math.pow(10,lb1-(g/4)*(lb1-lb0)):b1r-(g/4)*(b1r-b0r);
    const iv=i1-(g/4)*(i1-i0);
    grid+=`<line x1="${{mL}}" y1="${{y.toFixed(1)}}" x2="${{W-mR}}" y2="${{y.toFixed(1)}}" stroke="#1e2838"/>`;
    ax+=`<text x="${{mL-8}}" y="${{(y+4).toFixed(1)}}" fill="#4a9fd4" font-size="11" text-anchor="end" font-family="ui-monospace">${{bv>=1000?Math.round(bv).toLocaleString():bv.toFixed(bv>=100?0:1)}}</text>`;
    ax+=`<text x="${{W-mR+8}}" y="${{(y+4).toFixed(1)}}" fill="#e0913b" font-size="11" text-anchor="start" font-family="ui-monospace">${{Math.abs(iv)>=1000?Math.round(iv):iv.toFixed(1)}}</text>`;}}
  let xt='';for(let i=0;i<n;i+=Math.round(n/8)){{xt+=`<text x="${{X(i).toFixed(1)}}" y="${{H-8}}" fill="#6b7a90" font-size="10" text-anchor="middle" font-family="ui-monospace">${{D[i]}}</text>`;}}
  // 종합점수 선택 시: 0선 + 유불리 음영
  let shade='';
  const isScore=indK.indexOf('종합점수')>=0;
  if(isScore){{
    const zeroY=Yi(0);
    shade=`<rect x="${{mL}}" y="${{mT}}" width="${{W-mL-mR}}" height="${{zeroY-mT}}" fill="#3fb37f" opacity="0.06"/>`+
          `<rect x="${{mL}}" y="${{zeroY}}" width="${{W-mL-mR}}" height="${{H-mB-zeroY}}" fill="#e5484d" opacity="0.06"/>`+
          `<line x1="${{mL}}" y1="${{zeroY.toFixed(1)}}" x2="${{W-mR}}" y2="${{zeroY.toFixed(1)}}" stroke="#5f7291" stroke-dasharray="4 3"/>`+
          `<text x="${{W-mR-4}}" y="${{(zeroY-4).toFixed(1)}}" fill="#3fb37f" font-size="9.5" text-anchor="end" font-family="ui-monospace">유리</text>`+
          `<text x="${{W-mR-4}}" y="${{(zeroY+12).toFixed(1)}}" fill="#e5484d" font-size="9.5" text-anchor="end" font-family="ui-monospace">불리</text>`;
  }} else {{
    // 개별 지표: 유리/불리 경계선.
    //   명목지표(환율·유가·수출·통화량 등)는 통화량 팽창으로 장기 우상향하므로,
    //   수평 중앙값선으로 비교하면 옛날 낮은 값과 지금 높은 값을 같은 선으로 오판한다.
    //   → 이런 지표는 로그-선형 추세선(우상향)을 경계로 긋고, 나머지는 기존 수평 중앙값.
    const meta=DATA.ic[indK];
    // 방향이 검증된 신호만 유리/불리로 칠한다. 참고 지표(합성점수 미사용)는 방향을
    //   확인한 적이 없으므로 색으로 유불리를 주장하지 않고 중립(위/아래)으로만 표시한다.
    const hasDir=!!(meta&&meta.dir);
    const lowGood=hasDir&&meta.dir.indexOf('낮을')>=0;
    const upFill=hasDir?(lowGood?'#e5484d':'#3fb37f'):'#5f7291';
    const dnFill=hasDir?(lowGood?'#3fb37f':'#e5484d'):'#5f7291';
    const upLab=hasDir?(lowGood?'불리':'유리'):'위', dnLab=hasDir?(lowGood?'유리':'불리'):'아래';
    // 명목(추세성) 지표 목록 — 통화량과 연동돼 장기 우상향
    //   ※ 부분일치로 검사하므로 비율 지표('신용융자/예탁금')가 걸리지 않게 전체 표기를 쓴다
    const NOMINAL=['환율(원/달러)','WTI 유가','수출 YoY','수출금액','시가총액/M2','M2','M2/M1 비율','M2 증가율(YoY)',
                   '고객예탁금(조원)','신용융자(조원)','미수금(조원)'];
    const isNominal=NOMINAL.some(k=>indK.indexOf(k)>=0)||indK.indexOf('환율')>=0||indK.indexOf('유가')>=0;
    // 로그-선형 추세 적합 (양수 값만)
    let trend=null;
    if(isNominal){{
      let sx=0,sy=0,sxx=0,sxy=0,cnt=0;
      for(let i=0;i<n;i++){{const v=ind[i]; if(v==null||v<=0) continue;
        const ly=Math.log(v); sx+=i; sy+=ly; sxx+=i*i; sxy+=i*ly; cnt++;}}
      if(cnt>10){{const dn=cnt*sxx-sx*sx;
        if(Math.abs(dn)>1e-9){{const sl=(cnt*sxy-sx*sy)/dn, ic_=(sy-sl*sx)/cnt;
          trend={{slope:sl,intercept:ic_}};}}}}
    }}
    // 구조 단절 지표: 절단 이후 구간만으로 중앙값을 잡는다. 옛 제도 구간을 섞으면
    //   차트 경계선(중앙값)과 신호 분해(절단 후 z-score)가 서로 다른 답을 내놓는다.
    const cutFrom=meta&&meta.from;
    let cutIdx=-1;
    if(cutFrom){{ for(let i=0;i<n;i++){{ if(D[i]>=cutFrom){{ cutIdx=i; break; }} }} }}
    const ivSrc=(cutIdx>0)?ind.slice(cutIdx):ind;
    const iv=ivSrc.filter(v=>v!=null).sort((a,b)=>a-b);
    if(trend){{
      // 우상향 추세선: 각 x에서 exp(slope*i+intercept)
      const y0=Yi(Math.exp(trend.intercept)), y1v=Yi(Math.exp(trend.slope*(n-1)+trend.intercept));
      // 추세선 위/아래를 유불리 음영으로 (폴리곤)
      let above='M'+mL+' '+mT+' ', below='M'+mL+' '+(H-mB)+' ';
      let tpath='';
      for(let i=0;i<n;i++){{const ty=Yi(Math.exp(trend.slope*i+trend.intercept));
        tpath+=(i===0?'M':'L')+X(i).toFixed(1)+' '+ty.toFixed(1)+' ';}}
      // 위쪽 영역 폴리곤
      let poly='';
      for(let i=0;i<n;i++){{poly+=(i===0?'M':'L')+X(i).toFixed(1)+' '+Yi(Math.exp(trend.slope*i+trend.intercept)).toFixed(1)+' ';}}
      const polyUp=`${{poly}}L ${{(W-mR).toFixed(1)}} ${{mT}} L ${{mL}} ${{mT}} Z`;
      const polyDn=`${{poly}}L ${{(W-mR).toFixed(1)}} ${{(H-mB).toFixed(1)}} L ${{mL}} ${{(H-mB).toFixed(1)}} Z`;
      shade=`<path d="${{polyUp}}" fill="${{upFill}}" opacity="0.05"/>`+
            `<path d="${{polyDn}}" fill="${{dnFill}}" opacity="0.05"/>`+
            `<path d="${{tpath}}" fill="none" stroke="#5f7291" stroke-dasharray="4 3" stroke-width="1"/>`+
            `<text x="${{W-mR-4}}" y="${{(y1v-4).toFixed(1)}}" fill="${{upFill}}" font-size="9.5" text-anchor="end" font-family="ui-monospace">${{upLab}}</text>`+
            `<text x="${{W-mR-4}}" y="${{(y1v+12).toFixed(1)}}" fill="${{dnFill}}" font-size="9.5" text-anchor="end" font-family="ui-monospace">${{dnLab}}</text>`+
            `<text x="${{mL+4}}" y="${{(y0-4).toFixed(1)}}" fill="#8b98ab" font-size="9" font-family="ui-monospace">장기추세선</text>`;
    }} else if(iv.length>10){{
      const medV=iv[Math.floor(iv.length/2)];
      const medY=Yi(medV);
      shade=`<rect x="${{mL}}" y="${{mT}}" width="${{W-mL-mR}}" height="${{medY-mT}}" fill="${{upFill}}" opacity="0.05"/>`+
            `<rect x="${{mL}}" y="${{medY}}" width="${{W-mL-mR}}" height="${{H-mB-medY}}" fill="${{dnFill}}" opacity="0.05"/>`+
            `<line x1="${{mL}}" y1="${{medY.toFixed(1)}}" x2="${{W-mR}}" y2="${{medY.toFixed(1)}}" stroke="#5f7291" stroke-dasharray="4 3"/>`+
            `<text x="${{W-mR-4}}" y="${{(medY-4).toFixed(1)}}" fill="${{upFill}}" font-size="9.5" text-anchor="end" font-family="ui-monospace">${{upLab}}</text>`+
            `<text x="${{W-mR-4}}" y="${{(medY+12).toFixed(1)}}" fill="${{dnFill}}" font-size="9.5" text-anchor="end" font-family="ui-monospace">${{dnLab}}</text>`+
            `<text x="${{mL+4}}" y="${{(medY-4).toFixed(1)}}" fill="#8b98ab" font-size="9" font-family="ui-monospace">중앙값 ${{medV>=1000?Math.round(medV).toLocaleString():medV.toFixed(medV>=100?0:2)}}</text>`;
    }}
    // 구조 단절선: 제외 구간을 어둡게 덮고 세로 점선 + 사유 라벨
    if(cutIdx>0){{
      const cx=X(cutIdx);
      shade+=`<rect x="${{mL}}" y="${{mT}}" width="${{(cx-mL).toFixed(1)}}" height="${{H-mT-mB}}" fill="#0b0e14" opacity="0.45"/>`+
             `<line x1="${{cx.toFixed(1)}}" y1="${{mT}}" x2="${{cx.toFixed(1)}}" y2="${{H-mB}}" stroke="#e0913b" stroke-dasharray="3 3" stroke-width="1.2"/>`+
             `<text x="${{(cx-5).toFixed(1)}}" y="${{mT+11}}" fill="#8b98ab" font-size="9" text-anchor="end" font-family="ui-monospace">신호 제외</text>`+
             `<text x="${{(cx+5).toFixed(1)}}" y="${{mT+11}}" fill="#e0913b" font-size="9" font-family="ui-monospace">${{cutFrom}}~ 신호 사용</text>`;
    }}
  }}
  // ── 최신값 숫자 표시 ──
  //   지표마다 자릿수가 크게 달라(코스피 6,579 · VKOSPI 56.5 · 비율 0.30) 적응형 포맷을 쓴다.
  //   선 끝에 점과 숫자를 붙이고, 정보줄에도 기준 시점과 함께 텍스트로 적는다.
  const fmtV=v=>{{
    const a=Math.abs(v);
    if(a>=1000) return v.toLocaleString(undefined,{{maximumFractionDigits:0}});
    if(a>=10) return v.toFixed(1);      // 100.72조 → 100.7 (0자리로 자르면 101이 돼 어긋난다)
    return v.toFixed(2);
  }};
  const lastIdx=arr=>{{ for(let i=arr.length-1;i>=0;i--) if(arr[i]!=null) return i; return -1; }};
  const eb=lastIdx(base), ei=lastIdx(ind);
  let yb=eb>=0?Yb(base[eb]):null, yi=ei>=0?Yi(ind[ei]):null;
  // 두 라벨이 겹치면 위아래로 살짝 벌린다
  if(yb!=null&&yi!=null&&Math.abs(yb-yi)<13){{ if(yb<=yi){{yb-=7;yi+=7;}} else {{yb+=7;yi-=7;}} }}
  let endLab='';
  if(eb>=0) endLab+=`<circle cx="${{X(eb).toFixed(1)}}" cy="${{Yb(base[eb]).toFixed(1)}}" r="3.2" fill="#4a9fd4"/>`
    +`<text x="${{(X(eb)+6).toFixed(1)}}" y="${{(yb+3.5).toFixed(1)}}" fill="#4a9fd4" font-size="11" font-weight="600" font-family="ui-monospace">${{fmtV(base[eb])}}</text>`;
  if(ei>=0) endLab+=`<circle cx="${{X(ei).toFixed(1)}}" cy="${{Yi(ind[ei]).toFixed(1)}}" r="3.2" fill="#e0913b"/>`
    +`<text x="${{(X(ei)+6).toFixed(1)}}" y="${{(yi+3.5).toFixed(1)}}" fill="#e0913b" font-size="11" font-weight="600" font-family="ui-monospace">${{fmtV(ind[ei])}}</text>`;
  // 정보줄에 붙일 '오늘의 값' 문구
  const asOf=D[Math.max(eb,ei)]||D[D.length-1];
  const nowTxt=`<div class="ii-note" style="margin-top:4px">최신 <b>${{asOf}}</b> · `
    +(eb>=0?`<span style="color:#4a9fd4">${{baseK}} <b>${{fmtV(base[eb])}}</b></span>`:'')
    +(ei>=0?` · <span style="color:#e0913b">${{indK}} <b>${{fmtV(ind[ei])}}</b></span>`:'')+`</div>`;

  // 지표 정보(IC·가중치·방향 또는 점수 산출식)
  const info=document.getElementById('indInfo');
  if(isScore){{ info.innerHTML=`<b>종합점수</b> — ${{DATA.scoremeta.method}}`+nowTxt; }}
  else if(DATA.ic[indK]){{ const m=DATA.ic[indK];
    info.innerHTML=`<b>${{indK}}</b> · 예측력 IC <b>${{m.ic>=0?'+':''}}${{m.ic}}</b> · 최종가중 <b>${{m.w}}%</b> · ${{m.dir}} <span class="ii-note">(코스피 기준)</span>`
      +nowTxt
      +(m.fromWhy?`<div class="ii-note" style="margin-top:4px;line-height:1.45">⚠ <b>${{m.from}}~ 구간만 신호에 사용.</b> ${{m.fromWhy}}</div>`:''); }}
  else {{ info.innerHTML=`<b>${{indK}}</b> · 참고 지표 (합성점수 미사용)`+nowTxt; }}
  document.getElementById('chart').innerHTML=
    `<svg id="csvg" viewBox="0 0 ${{W}} ${{H}}">${{shade}}${{grid}}${{ax}}${{xt}}`+
    `<path d="${{path(base,Yb)}}" fill="none" stroke="#4a9fd4" stroke-width="1.8"/>`+
    `<path d="${{path(ind,Yi)}}" fill="none" stroke="#e0913b" stroke-width="1.8"/>`+
    endLab+
    `<g id="cg" style="display:none">`+
    `<line id="cline" y1="${{mT}}" y2="${{H-mB}}" stroke="#5f7291" stroke-width="1" stroke-dasharray="3 3"/>`+
    `<circle id="cdb" r="4.5" fill="#4a9fd4" stroke="#0e1420" stroke-width="1.5"/>`+
    `<circle id="cdi" r="4.5" fill="#e0913b" stroke="#0e1420" stroke-width="1.5"/></g>`+
    `<rect id="chit" x="${{mL}}" y="${{mT}}" width="${{W-mL-mR}}" height="${{H-mT-mB}}" fill="transparent"/></svg>`;
  document.getElementById('lgdBase').textContent=baseK;
  document.getElementById('lgdInd').textContent=indK;

  const svg=document.getElementById('csvg'), cg=document.getElementById('cg');
  const cline=document.getElementById('cline'), cdb=document.getElementById('cdb'), cdi=document.getElementById('cdi');
  const tip=document.getElementById('ctip'), hit=document.getElementById('chit');
  const fmt=v=>v==null?'—':(Math.abs(v)>=1000?Math.round(v).toLocaleString():(Math.abs(v)>=100?v.toFixed(0):v.toFixed(2)));
  function hide(){{cg.style.display='none';tip.style.display='none';}}
  hit.addEventListener('mousemove',ev=>{{
    const r=svg.getBoundingClientRect();
    const sx=(ev.clientX-r.left)/r.width*W;
    let i=Math.round((sx-mL)/(W-mL-mR)*(n-1));
    i=Math.max(0,Math.min(n-1,i));
    const bv=base[i], iv=ind[i];
    if(bv==null&&iv==null){{hide();return;}}
    const px=X(i);
    cg.style.display=''; cline.setAttribute('x1',px); cline.setAttribute('x2',px);
    if(bv==null){{cdb.style.display='none';}} else {{cdb.style.display='';cdb.setAttribute('cx',px);cdb.setAttribute('cy',Yb(bv));}}
    if(iv==null){{cdi.style.display='none';}} else {{cdi.style.display='';cdi.setAttribute('cx',px);cdi.setAttribute('cy',Yi(iv));}}
    tip.style.display='block';
    tip.innerHTML=`<div class="tp-d">${{D[i]}}</div>`+
      `<div class="tp-r"><i style="background:#4a9fd4"></i>${{baseK}}<b>${{fmt(bv)}}</b></div>`+
      `<div class="tp-r"><i style="background:#e0913b"></i>${{indK}}<b>${{fmt(iv)}}</b></div>`;
    const pxCss=px/W*r.width;
    const tw=tip.offsetWidth||150;
    tip.style.left=Math.max(4,Math.min(r.width-tw-4,pxCss-tw/2))+'px';
    tip.style.top='6px';
  }});
  hit.addEventListener('mouseleave',hide);
}}
document.getElementById('baseSel').onchange=draw;
document.getElementById('indSel').onchange=draw;
// 예측 밴드 선택용: 초기 구간(bin)을 현재 국면(CBIN)으로 설정
window.__CURBIN=window.__CURBIN||{{}};
for(const _ix of ['KOSPI','KOSDAQ']){{
  if(window.CBIN&&window.CBIN[_ix]!=null) window.__CURBIN[_ix]=window.CBIN[_ix];
}}
draw();
let rawBuilt=false;
async function doUpdate(){{
  const btn=document.getElementById('updBtn'), txt=document.getElementById('updTxt');
  const panel=document.getElementById('updPanel'), log=document.getElementById('updLog');
  panel.classList.add('on'); log.innerHTML='';
  const say=(m,c)=>{{log.innerHTML+=(c?`<span class="${{c}}">${{m}}</span>`:m)+'\\n';log.scrollTop=log.scrollHeight;}};
  // 로컬 서버가 있으면(집 PC) 직접 수집, 없으면(웹) 깃허브 액션으로 안내
  let local=false;
  try{{ const pr=await fetch('/api/ping'); local=pr.ok; }}catch(e){{ local=false; }}
  if(!local){{
    // ── 웹(github.io): 파이썬을 못 돌리므로 깃허브 액션을 실행하도록 안내 ──
    const host=location.hostname;               // maeraego.github.io
    const owner=host.split('.')[0];             // maeraego
    const repo=location.pathname.split('/').filter(Boolean)[0] || 'Kospi-dashboard';
    const actionUrl='https://github.com/'+owner+'/'+repo+'/actions';
    say('웹에서는 데이터 수집을 직접 실행할 수 없습니다.','hi');
    say('대신 깃허브에서 「대시보드 생성」 워크플로를 실행하면');
    say('클라우드가 최신 데이터로 다시 만들어 줍니다.');
    say('');
    say('버튼을 누르면 깃허브 액션 페이지가 열립니다 →','hi');
    say('  Run workflow 클릭 (원하면 예상순이익 입력)');
    const niHint=[]; 
    const n1=(document.getElementById('niY1').value||'').trim();
    const n2=(document.getElementById('niY2').value||'').trim();
    if(n1||n2) say('  예상순이익 '+(n1||'유지')+' / '+(n2||'유지')+' 를 칸에 입력하세요');
    // 새 탭으로 액션 페이지 열기
    window.open(actionUrl, '_blank');
    return;
  }}
  btn.disabled=true; txt.textContent='갱신 중…';
  say('데이터 수집을 시작합니다.','hi');
  say('보통 3~6분 걸립니다 (KRX·ECOS·FRED 순서로 수집).');
  say('창을 닫지 말고 기다려 주세요. 진행 상황이 아래에 실시간으로 표시됩니다.');
  say('');
  const _t0=Date.now();
  try{{
    const fv=(document.getElementById('fpeVal').value||'').trim();
    const n1=(document.getElementById('niY1').value||'').trim();
    const n2=(document.getElementById('niY2').value||'').trim();
    if(n1||n2) say('예상순이익 '+(n1||'유지')+' / '+(n2||'유지')+' 반영 예정','hi');
    else if(fv) say('예상PER '+fv+' 반영 예정','hi');
    const r=await fetch('/api/update',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{fwd_per: fv, ni_fy1: n1, ni_fy2: n2}})}});
    const d=await r.json();
    if(d.busy){{ say('이미 갱신이 진행 중입니다.','err');
      btn.disabled=false; txt.textContent='데이터 최신화'; return; }}
    if(!d.started){{ say('갱신을 시작하지 못했습니다.','err');
      btn.disabled=false; txt.textContent='데이터 최신화'; return; }}
    // 서버는 백그라운드로 실행. 진행 상황을 주기적으로 받아온다.
    let shown=0, dead=0;
    const poll=setInterval(async()=>{{
      let p;
      try{{ p=await (await fetch('/api/progress')).json(); dead=0; }}
      catch(e){{ if(++dead>20){{ clearInterval(poll);
        say('서버와 연결이 끊겼습니다. 콘솔 창을 확인하세요.','err');
        btn.disabled=false; txt.textContent='데이터 최신화'; }} return; }}
      const lines=(p.log||'').split('\\n');
      for(let i=shown;i<lines.length;i++){{ if(lines[i].trim()!=='') say(lines[i]); }}
      shown=lines.length;
      const mm=Math.floor(p.elapsed/60), ss=p.elapsed%60;
      const est = p.elapsed<360 ? ` / 예상 ~6:00` : '';
      txt.textContent=p.running?`${{p.step}} ${{mm}}:${{String(ss).padStart(2,'0')}}${{est}}`:'데이터 최신화';
      if(p.done){{
        clearInterval(poll);
        if(p.ok){{ say('','');say('갱신 완료. 새 데이터로 다시 불러옵니다…','ok');
          setTimeout(()=>location.reload(),1200); }}
        else {{ say('갱신 실패. 위 로그를 확인하세요.','err');
          btn.disabled=false; txt.textContent='데이터 최신화'; }}
      }}
    }},1000);
  }}catch(e){{ say('오류: '+e,'err'); btn.disabled=false; txt.textContent='데이터 최신화'; }}
}}
function toggleK(){{const w=document.getElementById('kWrap');
  w.style.display=w.style.display==='none'?'block':'none';}}
function toggleSE(){{const w=document.getElementById('seWrap');
  if(w) w.style.display=w.style.display==='none'?'block':'none';}}
// 계절 대시보드 파일명이 로컬(season_dashboard.html)과 웹(docs/season.html)에서 다르다.
// 웹 배포본은 index.html 이므로, 파일명이 dashboard.html 이면 로컬로 판단해 링크를 바꾼다.
(function(){{
  const a=document.getElementById('seaLink'); if(!a) return;
  const f=location.pathname.split('/').pop();
  if(f==='dashboard.html') a.href='season_dashboard.html';
}})();
function toggleD(){{const w=document.getElementById('dWrap');
  w.style.display=w.style.display==='none'?'block':'none';}}
function toggleG(){{const w=document.getElementById('gWrap');
  w.style.display=w.style.display==='none'?'block':'none';}}
function toggleW(){{const w=document.getElementById('wWrap');
  w.style.display=w.style.display==='none'?'block':'none';}}
function toggleRaw(){{const w=document.getElementById('rawWrap');
  const show=w.style.display==='none';w.style.display=show?'block':'none';
  if(show&&!rawBuilt){{buildRaw();rawBuilt=true;}}}}
function buildRaw(){{const cols=Object.keys(S);
  let h='<table class="raw"><thead><tr><th>월</th>'+cols.map(c=>`<th>${{c}}</th>`).join('')+'</tr></thead><tbody>';
  for(let i=D.length-1;i>=0;i--){{h+=`<tr><td>${{D[i]}}</td>`+cols.map(c=>{{const v=S[c][i];
    return `<td>${{v==null?'':(Math.abs(v)>=1000?Math.round(v).toLocaleString():v)}}</td>`;}}).join('')+'</tr>';}}
  document.getElementById('rawTable').innerHTML=h+'</tbody></table>';}}
function downloadCSV(){{const cols=Object.keys(S);
  let csv='월,'+cols.join(',')+'\\n';
  for(let i=0;i<D.length;i++){{csv+=D[i]+','+cols.map(c=>S[c][i]==null?'':S[c][i]).join(',')+'\\n';}}
  const blob=new Blob(['\\ufeff'+csv],{{type:'text/csv;charset=utf-8'}});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='kospi_dashboard_rawdata.csv';a.click();}}
</script>
</body></html>'''

with open(os.path.join(HERE, 'dashboard.html'), 'w', encoding='utf-8') as f:
    f.write(html_doc)
for ix, lab in [('KOSPI', '코스피'), ('KOSDAQ', '코스닥')]:
    a = analyze(ix); rl, _ = regime(a['pct'])
    print(f"{lab}: 점수 {a['cur']:+.2f} · 백분위 {a['pct']*100:.0f}% · {rl}")
print("생성 완료 → dashboard.html")
