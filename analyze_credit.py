# -*- coding: utf-8 -*-
"""
analyze_credit.py — 신용잔고·고객예탁금의 KOSPI/KOSDAQ 선행 예측력 분석

데이터: kofia_daily.parquet (1998-06-18~), krx_daily.parquet, ecos_monthly.parquet(M2)
호라이즌: 7일(5거래일)·1개월(21)·3개월(63)·6개월(126)·1년(252)

방법:
  1) 원자료 → 파생신호(비율/변화율)
  2) IC = 스피어만 상관(신호 t, 이후 h거래일 로그수익)
     - 겹침 표본이라 t값은 Newey-West(lag=h) 보정
  3) 실전형 신호 = expanding z-score(과거만, 최소 750거래일) → 5분위별 이후수익·승률
  4) M2는 발표지연 감안 2개월 시프트 후 사용

사용법: C:/python312/python.exe analyze_credit.py [kospi|kosdaq|both]
"""
import sys
import numpy as np
import pandas as pd

HORIZONS = {"7일": 5, "1개월": 21, "3개월": 63, "6개월": 126, "1년": 252}
MIN_Z = 750          # expanding z 최소 과거 표본(약 3년)
NQ = 5               # 분위 수


# ────────────────────────── 데이터 ──────────────────────────
def load():
    kf = pd.read_parquet("kofia_daily.parquet")
    kx = pd.read_parquet("krx_daily.parquet")
    ec = pd.read_parquet("ecos_monthly.parquet")

    df = kx.join(kf, how="inner").sort_index()

    # M2: 월별(조원) → 발표지연 2개월 반영해 시프트 후 일별 ffill
    m2 = ec["M2"].dropna().shift(2)
    df["M2"] = m2.reindex(df.index, method="ffill") * 1e12   # 조원 → 원

    # 시가총액 조원 → 원
    for c in ("KOSPI_시총", "KOSDAQ_시총"):
        df[c + "_원"] = df[c] * 1e12
    return df


def build_signals(df):
    """예측 후보 신호. 이름 앞의 부호 가설은 리포트에서 실측으로 확인."""
    S = {}
    x = df

    # ── 1. 원계열 (레벨) ──
    S["신용융자"] = x["신용융자"]
    S["신용융자_유가"] = x["신용융자_유가"]
    S["신용융자_코스닥"] = x["신용융자_코스닥"]
    S["고객예탁금"] = x["투자자예탁금"]

    # ── 2. 지수 대비 (사용자 요청) ──
    S["신용융자/KOSPI지수"] = x["신용융자"] / x["KOSPI_종가"]
    S["신용융자_유가/KOSPI지수"] = x["신용융자_유가"] / x["KOSPI_종가"]
    S["신용융자_코스닥/KOSDAQ지수"] = x["신용융자_코스닥"] / x["KOSDAQ_종가"]
    S["고객예탁금/KOSPI지수"] = x["투자자예탁금"] / x["KOSPI_종가"]

    # ── 3. 시가총액 대비 (레버리지 밀도) ──
    S["신용융자_유가/KOSPI시총"] = x["신용융자_유가"] / x["KOSPI_시총_원"]
    S["신용융자_코스닥/KOSDAQ시총"] = x["신용융자_코스닥"] / x["KOSDAQ_시총_원"]
    S["신용융자/전체시총"] = x["신용융자"] / (x["KOSPI_시총_원"] + x["KOSDAQ_시총_원"])
    S["고객예탁금/전체시총"] = x["투자자예탁금"] / (x["KOSPI_시총_원"] + x["KOSDAQ_시총_원"])

    # ── 4. 서로 간 비율 ──
    S["신용융자/고객예탁금"] = x["신용융자"] / x["투자자예탁금"]
    S["고객예탁금/신용융자"] = x["투자자예탁금"] / x["신용융자"]

    # ── 5. 통화량(M2) 대비 ──
    S["신용융자/M2"] = x["신용융자"] / x["M2"]
    S["고객예탁금/M2"] = x["투자자예탁금"] / x["M2"]
    S["(예탁금+RP)/M2"] = (x["투자자예탁금"] + x["RP잔고"]) / x["M2"]
    S["전체시총/M2"] = (x["KOSPI_시총_원"] + x["KOSDAQ_시총_원"]) / x["M2"]

    # ── 6. 변화율(모멘텀) ──
    for base, nm in [("신용융자", "신용융자"), ("투자자예탁금", "고객예탁금"),
                     ("신용융자_코스닥", "신용융자_코스닥")]:
        S[f"{nm}_3개월변화율"] = x[base] / x[base].shift(63) - 1
        S[f"{nm}_12개월변화율"] = x[base] / x[base].shift(252) - 1

    # ── 7. 스트레스/청산 지표 ──
    S["반대매매비중"] = x["반대매매비중"]
    S["미수금/예탁금"] = x["위탁매매미수금"] / x["투자자예탁금"]
    S["대주/신용융자"] = x["대주"] / x["신용융자"].replace(0, np.nan)
    S["예탁증권담보융자/시총"] = x["예탁증권담보융자"] / (x["KOSPI_시총_원"] + x["KOSDAQ_시총_원"])

    out = pd.DataFrame(S, index=x.index)
    return out.replace([np.inf, -np.inf], np.nan)


def fwd_returns(px):
    return {k: np.log(px.shift(-h) / px) for k, h in HORIZONS.items()}


# ────────────────────────── 통계 ──────────────────────────
def nw_tstat(y, lag):
    """평균이 0인지에 대한 Newey-West 보정 t값 (겹침 표본용)."""
    y = np.asarray(pd.Series(y).dropna(), float)
    n = len(y)
    if n < 30:
        return np.nan
    m = y.mean()
    e = y - m
    g0 = (e @ e) / n
    var = g0
    for L in range(1, min(lag, n - 1) + 1):
        g = (e[L:] @ e[:-L]) / n
        var += 2 * (1 - L / (lag + 1)) * g
    if var <= 0:
        return np.nan
    return m / np.sqrt(var / n)


def ic_table(sig, fwds):
    """신호별 × 호라이즌별 스피어만 IC와 Newey-West t값."""
    rows = []
    for name in sig.columns:
        s = sig[name]
        rec = {"신호": name}
        for hk, hv in HORIZONS.items():
            f = fwds[hk]
            d = pd.concat([s, f], axis=1).dropna()
            d.columns = ["s", "f"]
            if len(d) < 500:
                rec[hk] = np.nan; rec[hk + "_t"] = np.nan; rec[hk + "_n"] = len(d)
                continue
            ic = d["s"].corr(d["f"], method="spearman")
            # t값: 순위 곱 시계열의 평균 유의성으로 근사(겹침 보정)
            zs = (d["s"].rank(pct=True) - 0.5) * np.sqrt(12)
            zf = (d["f"].rank(pct=True) - 0.5) * np.sqrt(12)
            rec[hk] = ic
            rec[hk + "_t"] = nw_tstat(zs * zf, hv)
            rec[hk + "_n"] = len(d)
        rows.append(rec)
    return pd.DataFrame(rows).set_index("신호")


def expanding_z(s, minp=MIN_Z):
    """과거 정보만 사용하는 z-score (look-ahead 없음)."""
    mu = s.expanding(min_periods=minp).mean()
    sd = s.expanding(min_periods=minp).std()
    return ((s - mu) / sd).replace([np.inf, -np.inf], np.nan)


def quantile_table(z, f, nq=NQ):
    """분위별 이후수익 평균/승률. z는 expanding z(실전 구현 가능)."""
    d = pd.concat([z, f], axis=1).dropna()
    d.columns = ["z", "f"]
    if len(d) < 500:
        return None
    try:
        d["q"] = pd.qcut(d["z"].rank(method="first"), nq, labels=range(1, nq + 1))
    except ValueError:
        return None
    g = d.groupby("q", observed=True)["f"]
    return pd.DataFrame({"평균수익": g.mean(), "승률": g.apply(lambda v: (v > 0).mean()), "n": g.size()})


# ────────────────────────── 리포트 ──────────────────────────
def report(market, df, sig):
    px = df[f"{market}_종가"]
    fwds = fwd_returns(px)
    tbl = ic_table(sig, fwds)

    print("\n" + "=" * 108)
    print(f"■ {market} 예측 — 스피어만 IC (신호 t → 이후 수익).  괄호는 Newey-West t값 (|t|>2 유의)")
    print(f"  표본: {px.dropna().index[0].date()} ~ {px.dropna().index[-1].date()}")
    print("=" * 108)
    hdr = f"{'신호':<26}" + "".join(f"{h:>15}" for h in HORIZONS)
    print(hdr); print("-" * 108)
    for name, r in tbl.iterrows():
        line = f"{name:<26}"
        for h in HORIZONS:
            ic, t = r[h], r[h + "_t"]
            cell = "      —      " if pd.isna(ic) else f"{ic:+.3f}({t:+.1f})".rjust(15)
            line += cell
        print(line)

    # 12개월 |IC| 상위 신호의 분위 성과
    key = "1년"
    rank = tbl[key].abs().sort_values(ascending=False).dropna()
    print("\n" + "-" * 108)
    print(f"■ {market} — 1년 |IC| 상위 6개 신호의 분위별 이후 12개월 수익 (expanding z, 실전 구현 가능)")
    print("-" * 108)
    for name in rank.index[:6]:
        z = expanding_z(sig[name])
        q = quantile_table(z, fwds[key])
        if q is None:
            continue
        cur = z.dropna()
        cur_z = cur.iloc[-1] if len(cur) else np.nan
        cur_pct = (sig[name].dropna().rank(pct=True).iloc[-1]) * 100
        print(f"\n  · {name}   (IC {tbl.loc[name, key]:+.3f}, 현재 z={cur_z:+.2f}, 역사적 백분위 {cur_pct:.0f}%)")
        for qi, r in q.iterrows():
            bar = "█" * max(0, int(round(r['평균수익'] * 40)))
            print(f"      {qi}분위(낮음→높음)  평균 {r['평균수익']*100:+7.2f}%   승률 {r['승률']*100:5.1f}%   n={int(r['n']):5d}  {bar}")
    return tbl


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "both").lower()
    df = load()
    sig = build_signals(df)
    print(f"[데이터] {df.index[0].date()} ~ {df.index[-1].date()}  거래일 {len(df)}개, 신호 {sig.shape[1]}개")

    tables = {}
    for mk in (["KOSPI", "KOSDAQ"] if which == "both" else [which.upper()]):
        tables[mk] = report(mk, df, sig)

    # 현재 상태 요약
    print("\n" + "=" * 108)
    print("■ 현재 위치 (역사적 백분위, 100%=사상 최고 수준)")
    print("=" * 108)
    for name in sig.columns:
        s = sig[name].dropna()
        if len(s) < 500:
            continue
        pct = s.rank(pct=True).iloc[-1] * 100
        bar = "─" * int(pct / 2.5)
        print(f"  {name:<26} {pct:5.1f}%  {bar}")
    return tables


if __name__ == "__main__":
    main()
