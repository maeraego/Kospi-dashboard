# -*- coding: utf-8 -*-
"""
dram_history.py  -  DRAM 현물/계약 과거 월별 시계열 (추정)

TrendForce 는 과거 시계열을 유료로만 판다. 그래서 과거 구간은
직접 정리해 둔 앵커를 쓴다. 출처는 아래 두 파일이고, 뉴스·TrendForce
주간 발표 스냅샷을 모아 그 사이를 보간한 값이다.

  dram_aug04.html   DDR4/DDR5 16Gb 주봉 앵커 + 분기 계약 계단
  nand_aug04.html   (NAND - 여기서는 쓰지 않음)

즉 이 모듈이 주는 값은 전부 '추정'이다.
실측은 collect_dram.py 가 오늘부터 쌓는 dram_spot_weekly.parquet /
dram_contract.parquet 뿐이고, 차트에서는 둘을 반드시 구분해 그린다.

주봉 앵커 기준일: 2025-04-04 (week 0), 주 단위 증가.
"""
import datetime
import pandas as pd

WEEK0 = datetime.date(2025, 4, 4)

# (week, USD/chip) - 사이는 선형보간
SPOT_ANCHORS = {
    'DDR4 16Gb': [
        (0, 3.80), (4, 4.20), (7, 5.50), (9, 8.00), (12, 13.50), (16, 15.91),
        (20, 22.00), (24, 32.00), (28, 44.00), (32, 54.00), (36, 62.00),
        (38, 65.00), (41, 72.00), (45, 78.00), (47, 72.00), (49, 63.00),
        (51, 57.00), (52, 54.00), (53, 51.00), (54, 48.00), (55, 46.00),
        (56, 44.50), (57, 42.50), (58, 43.20), (59, 41.50), (60, 43.00),
        (61, 47.00), (62, 48.50), (63, 50.00), (64, 50.50), (65, 51.00),
        (66, 52.50), (67, 56.30), (68, 58.10), (69, 59.40), (70, 60.80),
    ],
    'DDR5 16Gb': [
        (0, 5.00), (4, 5.30), (8, 5.80), (12, 6.20), (16, 6.84), (20, 7.80),
        (24, 9.50), (28, 13.00), (30, 14.00), (34, 20.50), (36, 24.00),
        (38, 27.20), (41, 25.00), (44, 22.00), (47, 21.00), (50, 20.50),
        (52, 20.20), (53, 19.80), (54, 19.50), (55, 19.20), (56, 19.00),
        (57, 19.00), (58, 19.30), (59, 19.80), (60, 19.60), (61, 20.50),
        (62, 21.20), (63, 22.20), (64, 23.00), (65, 23.20), (66, 23.40),
        (67, 23.80), (68, 24.20), (69, 24.60), (70, 25.00),
    ],
}

# 계약가는 분기 단위로 고정되므로 계단 (start_week, end_week, USD)
CONTRACT_STEPS = {
    'DDR4 16Gb': [(0, 12, 4.00), (13, 25, 4.80), (26, 38, 5.50),
                  (39, 51, 9.00), (52, 55, 18.00), (56, 68, 23.40),
                  (69, 70, 27.00)],
    'DDR5 16Gb': [(0, 12, 5.50), (13, 25, 6.10), (26, 38, 7.00),
                  (39, 51, 10.15), (52, 55, 16.24), (56, 68, 21.11),
                  (69, 70, 24.38)],
}

LAST_WEEK = 70


def _week_date(w):
    return pd.Timestamp(WEEK0 + datetime.timedelta(weeks=w))


def _lerp(anchors):
    """주 단위로 선형보간한 Series."""
    out = {}
    for w in range(LAST_WEEK + 1):
        lo, hi = anchors[0], anchors[-1]
        for a, b in zip(anchors, anchors[1:]):
            if a[0] <= w <= b[0]:
                lo, hi = a, b
                break
        t = 1.0 if hi[0] == lo[0] else (w - lo[0]) / (hi[0] - lo[0])
        out[_week_date(w)] = lo[1] + t * (hi[1] - lo[1])
    return pd.Series(out).sort_index()


def _steps(steps):
    out = {}
    for s, e, p in steps:
        for w in range(s, min(e, LAST_WEEK) + 1):
            out[_week_date(w)] = p
    return pd.Series(out).sort_index()


def monthly():
    """월별 평균으로 리샘플한 (spot_df, contract_df) 반환. 값은 모두 추정."""
    spot = pd.DataFrame({k: _lerp(v) for k, v in SPOT_ANCHORS.items()})
    con = pd.DataFrame({k: _steps(v) for k, v in CONTRACT_STEPS.items()})
    return (spot.resample('MS').mean().round(2),
            con.resample('MS').mean().round(2))


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    s, c = monthly()
    print('=== 현물(추정) 월별 ===')
    print(s.tail(8))
    print()
    print('=== 계약(추정) 월별 ===')
    print(c.tail(8))
