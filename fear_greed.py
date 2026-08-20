# -*- coding: utf-8 -*-
"""공포탐욕지수(Fear & Greed) 산출 — 한국/미국, 최대한 긴 시계열.

CNN Fear & Greed Index의 7개 구성요소를 이 프로젝트가 가진 데이터로 재현한다.
CNN 원본은 2011년부터라 20년 분석이 불가능하고 과거값을 공개하지도 않으므로,
같은 방법론으로 직접 산출한다.

핵심 규칙 (build_dashboard.py와 동일한 원칙):
  - 각 구성요소는 expanding 백분위(과거만, 최소 250일)로 0~100 변환 → 룩어헤드 차단
  - 그날 쓸 수 있는 구성요소만 평균 (최소 4개) → 과거로 갈수록 요소는 줄지만 시계열은 길어짐
  - 0 = 극단적 공포, 100 = 극단적 탐욕

출력: fear_greed_daily.parquet
"""
import numpy as np
import pandas as pd

MIN_OBS = 250      # 백분위 산출 최소 표본 (1년)
MIN_COMP = 4       # 지수를 만들 최소 구성요소 수


def pctrank(s):
    """expanding 백분위(0~100). 과거 데이터만 쓴다."""
    r = s.expanding(min_periods=MIN_OBS).rank(pct=True) * 100
    return r


def kospi_daily():
    d = pd.read_parquet("krx_daily.parquet")
    d.index = pd.to_datetime(d.index)
    return d["KOSPI_종가"].dropna()


def build_korea():
    """한국 공포탐욕지수. 구성요소 7개."""
    px = kospi_daily()
    fred = pd.read_parquet("fred_daily.parquet")
    ecos = pd.read_parquet("ecos_daily.parquet")
    kofia = pd.read_parquet("kofia_daily.parquet")
    vk = pd.read_parquet("vkospi_daily.parquet")["VKOSPI"].dropna()

    c = {}

    # 1. 주가 모멘텀 — 125일 이동평균 대비 (CNN과 동일)
    c["모멘텀"] = px / px.rolling(125).mean() - 1

    # 2. 주가 강도 — 52주 고저 구간 내 위치
    lo, hi = px.rolling(252).min(), px.rolling(252).max()
    c["52주위치"] = (px - lo) / (hi - lo)

    # 3. 변동성 — VKOSPI가 50일 평균보다 낮으면 탐욕 (부호 반전)
    #    2003년 이전은 VKOSPI가 없어 실현변동성(20일)으로 대체한다.
    rv = np.log(px / px.shift(1)).rolling(20).std() * np.sqrt(252) * 100
    vol = vk.reindex(px.index).ffill(limit=5)
    vol = vol.fillna(rv)
    c["변동성"] = -(vol / vol.rolling(50).mean() - 1)

    # 4. 안전자산 선호 — 주식 20일수익 - 채권 20일수익(듀레이션 3년 근사)
    y3 = ecos["국고채3년"].reindex(px.index).ffill()
    bond20 = -(y3 - y3.shift(20)) * 3 / 100
    c["안전자산선호"] = (px / px.shift(20) - 1) - bond20

    # 5. 신용스프레드 — 좁을수록 위험선호(탐욕). 부호 반전
    c["신용스프레드"] = -ecos["신용스프레드"].reindex(px.index).ffill()

    # 6. 풋/콜 비율 — 낮을수록 탐욕. 부호 반전
    dv = pd.read_parquet("deriv_flow_daily.parquet")
    dv["date"] = pd.to_datetime(dv["date"])
    buy = dv[(dv["product"].isin(["코스피200콜", "코스피200풋"])) & (dv["measure"] == "매수")]
    t = buy.pivot_table(index="date", columns="product", values="전체", aggfunc="sum")
    pcr = (t["코스피200풋"] / t["코스피200콜"]).rolling(5).mean()
    c["풋콜비율"] = -pcr.reindex(px.index).ffill(limit=5)

    # 7. 투자자 레버리지 — 빚내서 산 돈 / 대기현금. 높을수록 탐욕
    #    T+1 공표라 하루 밀어서 쓴다 (룩어헤드 차단)
    lev = (kofia["신용융자"] / kofia["투자자예탁금"]).shift(1)
    c["레버리지"] = lev.reindex(px.index).ffill(limit=5)

    return assemble(c, px, "한국")


def build_us():
    """미국 공포탐욕지수. 구성요소 5개.
    브레드스(McClellan)와 풋/콜은 20년치 무료 데이터가 없어 제외."""
    f = pd.read_parquet("fred_daily.parquet")
    px = f["NASDAQ"].dropna()   # S&P500은 FRED가 최근 10년만 제공

    c = {}
    c["모멘텀"] = px / px.rolling(125).mean() - 1

    lo, hi = px.rolling(252).min(), px.rolling(252).max()
    c["52주위치"] = (px - lo) / (hi - lo)

    vix = f["VIX"].reindex(px.index).ffill()
    c["변동성"] = -(vix / vix.rolling(50).mean() - 1)

    y10 = f["US10Y"].reindex(px.index).ffill()
    bond20 = -(y10 - y10.shift(20)) * 7 / 100      # 듀레이션 7년 근사
    c["안전자산선호"] = (px / px.shift(20) - 1) - bond20

    # 정크본드 수요 — Baa와 Aaa 격차가 좁으면 위험선호(탐욕)
    # HY_OAS(BAMLH0A0HYM2)는 ICE 라이선스로 FRED가 최근 3년만 줘서 못 쓴다
    c["정크본드수요"] = -(f["BAA10Y"] - f["AAA10Y"]).reindex(px.index).ffill()

    return assemble(c, px, "미국")


def assemble(comps, px, label):
    raw = pd.DataFrame(comps).reindex(px.index)
    ranked = raw.apply(pctrank)
    n = ranked.notna().sum(axis=1)
    fg = ranked.mean(axis=1).where(n >= MIN_COMP)

    out = ranked.add_prefix("c_")
    out["구성요소수"] = n
    out["공포탐욕"] = fg
    valid = fg.dropna()
    print(f"[{label}] {valid.index.min().date()} ~ {valid.index.max().date()}  "
          f"({len(valid):,}일)  현재 {valid.iloc[-1]:.1f}")
    for c in raw.columns:
        s = ranked[c].dropna()
        print(f"    {c:<8s} {len(s):>5,}일  {s.index.min().date()}~  현재 {s.iloc[-1]:5.1f}")
    return out


def label_of(v):
    if v < 25:  return "극단적 공포"
    if v < 45:  return "공포"
    if v < 55:  return "중립"
    if v < 75:  return "탐욕"
    return "극단적 탐욕"


if __name__ == "__main__":
    kr = build_korea()
    print()
    us = build_us()

    both = pd.concat({"KR": kr, "US": us}, axis=1)
    both.columns = [f"{a}_{b}" for a, b in both.columns]
    both.to_parquet("fear_greed_daily.parquet")

    print("\n" + "=" * 60)
    for m, d in (("한국", kr), ("미국", us)):
        v = d["공포탐욕"].dropna().iloc[-1]
        print(f"{m}: {v:.1f}  →  {label_of(v)}")
    print("저장 → fear_greed_daily.parquet")
