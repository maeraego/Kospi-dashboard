# -*- coding: utf-8 -*-
"""
check_credit_tails.py — "팔 사람 다 팔았다" 가설의 꼬리 구간 검증

선형 IC는 전 구간 평균 관계만 본다. 사용자 직관("코스닥 신용잔고가 역사적 바닥이라
급등")은 분포의 극단 꼬리에 대한 주장이므로, 하위/상위 5·10%만 떼어 별도 검증한다.
비교 기준은 전체표본 평균이다.
"""
import numpy as np
import pandas as pd
from analyze_credit import load, build_signals, HORIZONS

WATCH = [
    "신용융자_코스닥_3개월변화율", "신용융자_코스닥_12개월변화율",
    "신용융자_코스닥/KOSDAQ시총", "신용융자_3개월변화율",
    "고객예탁금_3개월변화율", "신용융자/고객예탁금", "신용융자/M2",
]


def tail_stats(sig, px, name, market):
    s = sig[name]
    print(f"\n{'='*100}")
    cur_pct = s.dropna().rank(pct=True).iloc[-1] * 100
    print(f"■ {name}  →  {market}      현재 위치: 역사적 {cur_pct:.1f} 백분위")
    print(f"{'='*100}")
    print(f"{'구간':<18}" + "".join(f"{h:>15}" for h in HORIZONS))
    print("-" * 100)

    bands = [("하위 5% (극단바닥)", 0.00, 0.05), ("하위 10%", 0.00, 0.10),
             ("하위 25%", 0.00, 0.25), ("전체평균", 0.00, 1.00),
             ("상위 25%", 0.75, 1.00), ("상위 10%", 0.90, 1.00),
             ("상위 5% (극단과열)", 0.95, 1.00)]

    pct = s.rank(pct=True)
    for label, lo, hi in bands:
        mask = (pct > lo) & (pct <= hi) if lo > 0 else (pct <= hi)
        line = f"{label:<18}"
        for hk, hv in HORIZONS.items():
            f = np.log(px.shift(-hv) / px)
            v = f[mask].dropna()
            if len(v) < 30:
                line += f"{'—':>15}"
            else:
                win = (v > 0).mean() * 100
                line += f"{v.mean()*100:+6.1f}% {win:3.0f}%".rjust(15)
        print(line)
    print(f"{'':<18}" + "".join(f"{'평균 승률':>15}" for _ in HORIZONS))


def main():
    df = load()
    sig = build_signals(df)
    print(f"[표본] {df.index[0].date()} ~ {df.index[-1].date()}")
    print("각 칸 = 해당 구간 진입 후 평균 로그수익 / 승률")

    for name in WATCH:
        if name not in sig:
            continue
        mk = "KOSDAQ" if "코스닥" in name else "KOSPI"
        tail_stats(sig, df[f"{mk}_종가"], name, mk)

    # 코스닥 신용 바닥 국면이 실제 언제였는지, 그리고 그 후 1년
    print(f"\n{'='*100}")
    print("■ 코스닥 신용융자 3개월변화율 하위 5% 국면 — 시기별 이후 12개월 KOSDAQ 수익")
    print(f"{'='*100}")
    s = sig["신용융자_코스닥_3개월변화율"]
    px = df["KOSDAQ_종가"]
    f12 = np.log(px.shift(-252) / px)
    mask = s.rank(pct=True) <= 0.05
    ep = mask.astype(int).diff().fillna(0)
    starts = s.index[ep > 0]
    for st in starts:
        seg = mask.loc[st:]
        end = seg.idxmin() if (~seg).any() else seg.index[-1]
        if (end - st).days < 10:
            continue
        r = f12.loc[st]
        print(f"  {st.date()} ~ {end.date()}  ({(end-st).days:4d}일)   진입시 KOSDAQ {px.loc[st]:8.2f}"
              f"   이후 12개월 {('%+.1f%%' % (r*100)) if pd.notna(r) else '  (진행중)'}")


if __name__ == "__main__":
    main()
