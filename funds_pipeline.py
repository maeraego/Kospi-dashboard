# -*- coding: utf-8 -*-
"""
funds_pipeline.py  —  증시주변자금(신용잔고·예탁금) → KOSPI/KOSDAQ 예측 신호 대시보드
================================================================================
실행:  C:\\python312\\python.exe funds_pipeline.py all
       (fetch = funds.parquet 생성, analyze = 분석+HTML)

수집에 대하여
--------------
초안(HANDOFF.md)은 FreeSIS가 WebSquare 앱이라 Playwright로 XHR을 1회 캡처해
FREESIS 딕셔너리에 붙이라고 했으나, 실제로는 브라우저 없이 API를 직접 호출할 수 있다.
그 수집기가 collect_kofia.py 이고 kofia_daily.parquet 을 만든다(1998-06-18~).
따라서 이 파일은 캡처 단계 없이 kofia_daily.parquet 을 읽어 funds.parquet 을 만든다.

  · 엔드포인트 : POST https://freesis.kofia.or.kr/meta/getMetaDataList.do
  · 함정       : tmpV40/tmpV41 을 안 보내면 값이 전부 null 로 온다(날짜만 옴)
  · 함정       : 응답이 약 32KB에서 잘린다 → 기간 재귀 분할로 회피
  상세는 collect_kofia.py 주석 참조.

방법론 메모
------------
· T+1 공표: FreeSIS 자금 수치는 다음 영업일 공표 → 모든 신호에 shift(1) 적용.
  (이 보정이 없으면 7일 IC가 하루치 룩어헤드로 부풀려진다.)
· 정규화는 레벨 비율로만. 원계열 로그차분을 시총으로 나눈 뒤 차분하면
  −지수수익률이 기계적으로 주입돼 허위 음의 상관이 생긴다.
· z-score 는 expanding(과거만). 합성점수의 IC 가중도 과거 구간에서만 추정한다.
· 호라이즌별로 부호가 뒤집힌다(단기=모멘텀, 장기=역발상)는 것이 실측 결과라
  합성점수를 '단기'와 '장기' 둘로 분리한다. 하나로 합치면 서로 상쇄된다.
"""
import os, sys, json
import numpy as np
import pandas as pd

KOFIA_PARQUET = "kofia_daily.parquet"
KRX_PARQUET   = "krx_daily.parquet"
ECOS_PARQUET  = "ecos_monthly.parquet"
FUNDS_PARQUET = "funds.parquet"
OUT_HTML      = "fund_signal_dashboard.html"

HORIZONS = {"7일": 5, "1개월": 21, "3개월": 63, "6개월": 126, "1년": 252}
MIN_Z    = 750     # expanding z 최소 과거표본(약 3년)
PUB_LAG  = 1       # T+1 공표

# 합성점수 구성: (신호명, 방향)  방향 +1 = 값이 클수록 강세
SHORT_SPEC = [("고객예탁금_3개월변화율", +1), ("신용융자_3개월변화율", +1),
              ("신용융자/고객예탁금", -1)]
LONG_SPEC  = [("신용융자/고객예탁금", -1), ("신용융자_12개월변화율", -1),
              ("신용융자/M2", -1)]


# ── 1. 데이터 ────────────────────────────────────────────────────────────────
def build_funds_parquet():
    if not os.path.exists(KOFIA_PARQUET):
        raise SystemExit(f"[중단] {KOFIA_PARQUET} 없음. 먼저 collect_kofia.py 를 실행하세요.")
    kf = pd.read_parquet(KOFIA_PARQUET)
    out = pd.DataFrame({
        "신용잔고":       kf["신용융자"],
        "신용잔고_유가":   kf["신용융자_유가"],
        "신용잔고_코스닥": kf["신용융자_코스닥"],
        "예탁금":         kf["투자자예탁금"],
        "미수금":         kf["위탁매매미수금"],
        "반대매매비중":    kf["반대매매비중"],
        "RP잔고":        kf["RP잔고"],
        "대주":          kf["대주"],
    })
    out.index.name = "날짜"
    out.to_parquet(FUNDS_PARQUET)
    print(f"[저장] {FUNDS_PARQUET}  shape={out.shape}  "
          f"{out.index.min().date()} ~ {out.index.max().date()}")
    return out


def load_all():
    funds = pd.read_parquet(FUNDS_PARQUET)
    krx   = pd.read_parquet(KRX_PARQUET)
    ecos  = pd.read_parquet(ECOS_PARQUET)
    df = krx.join(funds, how="inner").sort_index()
    m2 = ecos["M2"].dropna().shift(2)                     # 발표지연 2개월
    df["M2"] = m2.reindex(df.index, method="ffill") * 1e12
    df["KOSPI_시총원"]  = df["KOSPI_시총"] * 1e12
    df["KOSDAQ_시총원"] = df["KOSDAQ_시총"] * 1e12
    return df


def build_signals(df):
    x, S = df, {}
    S["신용잔고"] = x["신용잔고"]
    S["고객예탁금"] = x["예탁금"]
    S["신용잔고/KOSPI지수"] = x["신용잔고"] / x["KOSPI_종가"]
    S["신용잔고_코스닥/KOSDAQ지수"] = x["신용잔고_코스닥"] / x["KOSDAQ_종가"]
    S["신용잔고_유가/KOSPI시총"] = x["신용잔고_유가"] / x["KOSPI_시총원"]
    S["신용잔고_코스닥/KOSDAQ시총"] = x["신용잔고_코스닥"] / x["KOSDAQ_시총원"]
    S["신용융자/고객예탁금"] = x["신용잔고"] / x["예탁금"]
    S["신용융자/M2"] = x["신용잔고"] / x["M2"]
    S["고객예탁금/M2"] = x["예탁금"] / x["M2"]
    S["전체시총/M2"] = (x["KOSPI_시총원"] + x["KOSDAQ_시총원"]) / x["M2"]
    for base, nm in [("신용잔고", "신용융자"), ("예탁금", "고객예탁금"),
                     ("신용잔고_코스닥", "신용융자_코스닥")]:
        S[f"{nm}_3개월변화율"] = x[base] / x[base].shift(63) - 1
        S[f"{nm}_12개월변화율"] = x[base] / x[base].shift(252) - 1
    S["반대매매비중"] = x["반대매매비중"]
    S["미수금/예탁금"] = x["미수금"] / x["예탁금"]
    S["대주/신용잔고"] = x["대주"] / x["신용잔고"].replace(0, np.nan)

    sig = pd.DataFrame(S, index=x.index).replace([np.inf, -np.inf], np.nan)
    return sig.shift(PUB_LAG)          # ★ T+1 공표 반영


def fwd_returns(px):
    return {k: np.log(px.shift(-h) / px) for k, h in HORIZONS.items()}


def expanding_z(s, minp=MIN_Z):
    mu = s.expanding(min_periods=minp).mean()
    sd = s.expanding(min_periods=minp).std()
    return ((s - mu) / sd).replace([np.inf, -np.inf], np.nan)


# ── 2. 통계 ──────────────────────────────────────────────────────────────────
def nw_tstat(y, lag):
    """겹침 표본에서 평균이 0인지에 대한 Newey-West 보정 t값."""
    y = np.asarray(pd.Series(y).dropna(), float)
    n = len(y)
    if n < 30:
        return np.nan
    e = y - y.mean()
    var = (e @ e) / n
    for L in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - L / (lag + 1)) * ((e[L:] @ e[:-L]) / n)
    return y.mean() / np.sqrt(var / n) if var > 0 else np.nan


def ic_row(s, fwds):
    from scipy.stats import spearmanr
    rec = {}
    for hk, hv in HORIZONS.items():
        d = pd.concat([s, fwds[hk]], axis=1).dropna()
        d.columns = ["s", "f"]
        if len(d) < 500:
            rec[hk] = rec[hk + "_t"] = None
            continue
        ic = spearmanr(d["s"], d["f"]).statistic
        zs = (d["s"].rank(pct=True) - .5) * np.sqrt(12)
        zf = (d["f"].rank(pct=True) - .5) * np.sqrt(12)
        rec[hk] = round(float(ic), 3)
        t = nw_tstat(zs * zf, hv)
        rec[hk + "_t"] = None if pd.isna(t) else round(float(t), 1)
    return rec


def tail_row(s, px):
    """하위/상위 5% 진입 후 성과(꼬리 검증). 선형 IC가 놓치는 극단을 본다."""
    pct = s.rank(pct=True)
    out = {}
    for label, mask in [("lo", pct <= .05), ("mid", pct.notna()), ("hi", pct > .95)]:
        cell = {}
        for hk, hv in HORIZONS.items():
            v = np.log(px.shift(-hv) / px)[mask].dropna()
            cell[hk] = None if len(v) < 30 else [round(float(v.mean()) * 100, 1),
                                                 round(float((v > 0).mean()) * 100)]
        out[label] = cell
    return out


# ── 3. 선후상관 CCF (prewhitening) ───────────────────────────────────────────
def prewhiten_ccf(driver, response, maxlag=20, maxp=8):
    """driver 를 AR(p)로 백색화하고 같은 필터를 response 에 적용해 CCF 계산.
    peak_lag > 0 : driver 가 response 를 선행."""
    from scipy.signal import lfilter
    from statsmodels.tsa.arima.model import ARIMA
    d, r = driver.dropna(), response.dropna()
    idx = d.index.intersection(r.index)
    d, r = d.loc[idx], r.loc[idx]
    if len(idx) < maxlag * 4:
        return None
    p, best = 1, np.inf
    for pp in range(1, maxp + 1):
        try:
            b = ARIMA(d.values, order=(pp, 0, 0)).fit().bic
            if b < best:
                best, p = b, pp
        except Exception:
            pass
    fit = ARIMA(d.values, order=(p, 0, 0)).fit()
    a = pd.Series(fit.resid, index=d.index)
    b = np.concatenate([[1.0], -fit.arparams])
    beta = pd.Series(lfilter(b, [1.0], (r - r.mean()).values), index=r.index)
    a, beta = a.iloc[p:], beta.iloc[p:]
    av = (a - a.mean()).values
    bv = (beta - beta.mean()).values
    n, sa, sb = len(av), av.std(), bv.std()
    lags, cc = [], []
    for k in range(-maxlag, maxlag + 1):
        if n - abs(k) <= 0:
            c = np.nan
        else:
            c = np.mean(av[:n - k] * bv[k:]) if k >= 0 else np.mean(av[-k:] * bv[:n + k])
        lags.append(k); cc.append(c / (sa * sb) if sa and sb else np.nan)
    cc = np.array(cc)
    conf = 1.96 / np.sqrt(n)
    pi = int(np.nanargmax(np.abs(cc)))
    return dict(lags=[int(v) for v in lags], ccf=[round(float(v), 4) for v in cc],
                conf=round(float(conf), 4), peak_lag=int(lags[pi]),
                peak_corr=round(float(cc[pi]), 4), sig=bool(abs(cc[pi]) > conf), n=int(n))


# ── 4. 합성점수 (walk-forward IC 가중) ───────────────────────────────────────
def composite(sig, spec, px, horizon_key, refit_every=252, min_hist=1250):
    """구성신호 = 방향정렬 expanding z. 가중 = 과거구간에서만 추정한 |IC|.
    가중 추정 시점 T 에서는 forward 창이 T 이전에 끝난 표본만 쓴다(룩어헤드 차단)."""
    from scipy.stats import spearmanr
    h = HORIZONS[horizon_key]
    fwd = np.log(px.shift(-h) / px)
    zs = {n: (expanding_z(sig[n]) * d).clip(-3, 3) for n, d in spec if n in sig}
    if not zs:
        return None
    Z = pd.DataFrame(zs)

    score = pd.Series(np.nan, index=Z.index)
    marks = list(range(min_hist, len(Z), refit_every))
    for i, start in enumerate(marks):
        asof = Z.index[start]
        cutoff = Z.index[max(0, start - h)]        # forward 창이 asof 전에 끝난 지점까지만
        w = {}
        for c in Z.columns:
            d = pd.concat([Z[c].loc[:cutoff], fwd.loc[:cutoff]], axis=1).dropna()
            if len(d) < 250:
                continue
            ic = spearmanr(d.iloc[:, 0], d.iloc[:, 1]).statistic
            if pd.notna(ic):
                w[c] = abs(ic)
        if not w or sum(w.values()) == 0:
            continue
        end = Z.index[marks[i + 1]] if i + 1 < len(marks) else Z.index[-1]
        seg = Z.loc[asof:end, list(w)]
        wt = pd.Series(w) / sum(w.values())
        score.loc[asof:end] = (seg * wt).sum(axis=1, min_count=1)
    return score


def quantile_perf(score, px, horizon_key, nq=5):
    h = HORIZONS[horizon_key]
    f = np.log(px.shift(-h) / px)
    d = pd.concat([score, f], axis=1).dropna()
    d.columns = ["s", "f"]
    if len(d) < 300:
        return None
    try:
        d["q"] = pd.qcut(d["s"].rank(method="first"), nq, labels=range(1, nq + 1))
    except ValueError:
        return None
    g = d.groupby("q", observed=True)["f"]
    return [{"q": int(q), "ret": round(float(m) * 100, 2),
             "win": round(float(w) * 100, 1), "n": int(n)}
            for q, m, w, n in zip(g.mean().index, g.mean(),
                                  g.apply(lambda v: (v > 0).mean()), g.size())]


# ── 5. 실행 ──────────────────────────────────────────────────────────────────
def analyze_and_render():
    if not os.path.exists(FUNDS_PARQUET):
        raise SystemExit(f"[중단] {FUNDS_PARQUET} 없음. funds_pipeline.py fetch 먼저.")
    df = load_all()
    sig = build_signals(df)
    print(f"[분석] {df.index[0].date()} ~ {df.index[-1].date()}  "
          f"거래일 {len(df)}  신호 {sig.shape[1]}  (T+{PUB_LAG} 공표 반영)")

    bundle = {"span": [df.index.min().strftime("%Y-%m-%d"),
                       df.index.max().strftime("%Y-%m-%d")],
              "markets": {}}

    for mk in ("KOSPI", "KOSDAQ"):
        px = df[f"{mk}_종가"]
        fwds = fwd_returns(px)
        rows = []
        for name in sig.columns:
            rows.append({"signal": name, **ic_row(sig[name], fwds)})
        rows.sort(key=lambda r: abs(r.get("1년") or 0), reverse=True)

        tails = {n: tail_row(sig[n], px)
                 for n in ["신용융자/고객예탁금", "신용융자_코스닥_12개월변화율",
                           "신용융자_코스닥_3개월변화율", "신용융자/M2",
                           "고객예탁금_3개월변화율"] if n in sig}

        comps = {}
        for label, spec, hk in [("단기(3개월)", SHORT_SPEC, "3개월"),
                                ("장기(1년)", LONG_SPEC, "1년")]:
            sc = composite(sig, spec, px, hk)
            if sc is None:
                continue
            q = quantile_perf(sc, px, hk)
            cur = sc.dropna()
            comps[label] = {"quantiles": q,
                            "current": None if not len(cur) else round(float(cur.iloc[-1]), 2),
                            "current_pct": None if not len(cur) else
                            round(float(cur.rank(pct=True).iloc[-1]) * 100, 1),
                            "members": [n for n, _ in spec if n in sig],
                            "horizon": hk}
        bundle["markets"][mk] = {"ic": rows, "tails": tails, "composite": comps}

    # CCF: Δ자금(로그차분) → 코스피 로그수익률
    lrK = np.log(df["KOSPI_종가"]).diff()
    ccf = []
    for c in ["신용잔고", "예탁금", "신용잔고_코스닥"]:
        d = np.log(df[c].where(df[c] > 0)).diff().shift(PUB_LAG)
        r = prewhiten_ccf(d, lrK, maxlag=20)
        if r:
            ccf.append({"signal": f"Δ{c}(로그차분)", **r})
    bundle["ccf"] = ccf

    # 현재 위치
    pos = []
    for name in sig.columns:
        s = sig[name].dropna()
        if len(s) < 500:
            continue
        pos.append({"signal": name, "pct": round(float(s.rank(pct=True).iloc[-1]) * 100, 1)})
    pos.sort(key=lambda r: -r["pct"])
    bundle["position"] = pos

    # 차트 계열(월말)
    def ser(s):
        s = s.dropna().resample("ME").last().dropna()
        return [[d.strftime("%Y-%m"), round(float(v), 6)] for d, v in s.items()]
    bundle["series"] = {
        "KOSPI(log)": ser(np.log(df["KOSPI_종가"])),
        "KOSDAQ(log)": ser(np.log(df["KOSDAQ_종가"])),
        "신용잔고(조원)": ser(df["신용잔고"] / 1e12),
        "예탁금(조원)": ser(df["예탁금"] / 1e12),
    }
    bundle["ratio"] = {
        "신용융자/고객예탁금": ser(sig["신용융자/고객예탁금"]),
        "KOSPI(log)": ser(np.log(df["KOSPI_종가"])),
    }
    bundle["kosdaq_credit"] = {
        "신용융자_코스닥_12개월변화율": ser(sig["신용융자_코스닥_12개월변화율"]),
        "KOSDAQ(log)": ser(np.log(df["KOSDAQ_종가"])),
    }

    open(OUT_HTML, "w", encoding="utf-8").write(
        HTML_TEMPLATE.replace("__DATA__", json.dumps(bundle, ensure_ascii=False)))
    print(f"[완료] {OUT_HTML}")

    k = bundle["markets"]["KOSPI"]["ic"]
    print("KOSPI 1년 |IC| 상위:", [(r["signal"], r["1년"]) for r in k[:5]])
    for m in ("KOSPI", "KOSDAQ"):
        for lbl, c in bundle["markets"][m]["composite"].items():
            print(f"  {m} 합성 {lbl}: 현재 {c['current']} ({c['current_pct']}%)  "
                  f"분위수익 {[q['ret'] for q in (c['quantiles'] or [])]}")
    if ccf:
        print("CCF:", [(c["signal"], c["peak_lag"], c["peak_corr"], c["sig"]) for c in ccf])


HTML_TEMPLATE = r'''<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>증시주변자금 → KOSPI/KOSDAQ 예측 신호</title>
<style>
:root{--bg:#0b0e14;--panel:#141924;--ink:#e6ebf2;--dim:#8a94a6;--grid:#232b3b;
--a:#f5b64a;--b:#3d7bff;--c:#2ec28a;--d:#e0455e;--line:#202737}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,"Segoe UI","Malgun Gothic",sans-serif;font-size:14px;line-height:1.5}
.wrap{max-width:1180px;margin:0 auto;padding:22px 18px 70px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--dim);font-size:12.5px;margin-bottom:18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:15px 16px;margin-bottom:14px}
.card h2{font-size:13.5px;margin:0 0 4px}
.note{color:var(--dim);font-size:11.5px;margin-bottom:10px}
svg{display:block;width:100%;height:auto}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px;min-width:640px}
th,td{padding:6px 8px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--panel)}
th{color:var(--dim);font-size:11.5px;font-weight:600}
.pos{color:var(--c)}.neg{color:var(--d)}.mut{color:var(--dim)}
.tag{color:var(--dim);font-size:11px}
.bar{height:7px;border-radius:4px;background:var(--b);display:inline-block;vertical-align:middle}
.leg span{margin-right:14px;font-size:11.5px}
b.st{color:var(--a)}
</style>
<div class="wrap">
<h1>증시주변자금 → KOSPI/KOSDAQ 예측 신호 <span class="tag" id="span"></span></h1>
<div class="sub">금융투자협회 FreeSIS 일별 신용잔고·고객예탁금. 신호는 T+1 공표 반영(shift 1),
z-score는 과거만 사용(expanding). 과거 통계이지 투자권유가 아닙니다.</div>

<div class="card"><h2>① 계열 추이 (월말)</h2>
<div class="note">각 계열을 자기 범위로 정규화해 겹쳐 그림. 수준이 아니라 모양을 비교하세요.</div>
<div id="c1"></div><div class="leg" id="l1" style="margin-top:6px"></div></div>

<div class="card"><h2>② 핵심 신호 — 신용융자/고객예탁금 vs KOSPI</h2>
<div class="note">빚(신용융자) ÷ 대기현금(예탁금). 상위 5%(빨강)=레버리지 과열, 하위 5%(초록)=청산 완료.</div>
<div id="c2"></div><div class="leg" id="l2" style="margin-top:6px"></div></div>

<div class="card"><h2>③ 코스닥 신용잔고 12개월 변화율 vs KOSDAQ</h2>
<div class="note">"팔 사람 다 팔았나"를 보는 창. 하위 구간(초록)에서 이후 1년 성과가 가장 좋았습니다.</div>
<div id="c3"></div><div class="leg" id="l3" style="margin-top:6px"></div></div>

<div class="card"><h2>④ 신호별 IC (스피어만, 괄호는 Newey-West t)</h2>
<div class="note">IC = 신호 순위와 이후 수익 순위의 상관. |t|&gt;2 를 유의로 봅니다.
단기에 +, 장기에 − 로 부호가 뒤집히는 신호가 많다는 점에 주목하세요.</div>
<div id="mk" style="margin-bottom:8px"></div>
<div class="scroll"><table id="tic"><thead></thead><tbody></tbody></table></div></div>

<div class="card"><h2>⑤ 꼬리 검증 — 극단 구간 진입 후 성과</h2>
<div class="note">선형 IC는 평균 관계만 본다. "역사적 바닥" 같은 주장은 꼬리에서 직접 확인해야 한다.
각 칸 = 평균수익 / 승률.</div>
<div class="scroll"><table id="ttail"><thead></thead><tbody></tbody></table></div></div>

<div class="card"><h2>⑥ 합성점수 — 분위별 이후 성과</h2>
<div class="note">구성신호를 방향 정렬 후 |IC| 가중. 가중치는 과거 구간에서만 추정(walk-forward).
호라이즌별 부호 반전 때문에 단기·장기를 분리했습니다.</div>
<div id="comp"></div></div>

<div class="card"><h2>⑦ 선후상관 CCF (Δ자금 → KOSPI 수익률)</h2>
<div class="note">AR 백색화 후 교차상관. peak_lag&gt;0 이면 자금이 지수를 선행, &lt;0 이면 지수가 자금을 선행.</div>
<div class="scroll"><table id="tccf">
<thead><tr><th>신호</th><th>peak_lag(일)</th><th>peak_corr</th><th>95% 임계</th><th>유의</th></tr></thead>
<tbody></tbody></table></div></div>

<div class="card"><h2>⑧ 현재 위치 (역사적 백분위)</h2>
<div class="note">100% = 사상 최고 수준. 자금 데이터 기준일은 상단 기간의 끝입니다.</div>
<div id="pos"></div></div>
</div>
<script>
const D=__DATA__;
const HZ=["7일","1개월","3개월","6개월","1년"];
document.getElementById('span').textContent='· '+D.span[0]+' ~ '+D.span[1];
const COL=['var(--a)','var(--b)','var(--c)','var(--d)'];
const lin=(v,a,b,p,q)=>p+(v-a)/((b-a)||1)*(q-p);
const ext=a=>{let m=1e18,x=-1e18;for(const[,v]of a){if(v<m)m=v;if(v>x)x=v}return[m,x]};

function chart(elId,legId,obj,shade){
  const keys=Object.keys(obj),W=1120,H=300,L=42,R=14,T=12,B=26;
  let all=[];keys.forEach(k=>all=all.concat(obj[k].map(d=>d[0])));
  const xs=[...new Set(all)].sort(),xi=Object.fromEntries(xs.map((d,i)=>[d,i])),n=xs.length;
  const xp=i=>lin(i,0,n-1,L,W-R);
  let g='',ly=null;
  xs.forEach((d,i)=>{const y=+d.slice(0,4);
    if(y!==ly&&y%5===0){ly=y;
      g+=`<line x1="${xp(i).toFixed(1)}" y1="${T}" x2="${xp(i).toFixed(1)}" y2="${H-B}" stroke="var(--grid)"/>`;
      g+=`<text x="${xp(i).toFixed(1)}" y="${H-8}" fill="var(--dim)" font-size="10" text-anchor="middle">${y}</text>`}
    else if(y!==ly)ly=y});
  if(shade){const s=obj[shade.key],v=s.map(d=>d[1]).slice().sort((a,b)=>a-b);
    const lo=v[Math.floor(v.length*0.05)],hi=v[Math.floor(v.length*0.95)];
    s.forEach(d=>{if(!(d[0]in xi))return;const x=xp(xi[d[0]]);
      if(d[1]>=hi)g+=`<rect x="${(x-2).toFixed(1)}" y="${T}" width="4" height="${H-B-T}" fill="var(--d)" opacity="0.16"/>`;
      else if(d[1]<=lo)g+=`<rect x="${(x-2).toFixed(1)}" y="${T}" width="4" height="${H-B-T}" fill="var(--c)" opacity="0.16"/>`})}
  keys.forEach((k,ki)=>{const s=obj[k],[a0,a1]=ext(s),yp=v=>lin(v,a0,a1,H-B,T);
    let p='',st=false;
    s.forEach(d=>{if(!(d[0]in xi))return;
      p+=(st?'L':'M')+xp(xi[d[0]]).toFixed(1)+' '+yp(d[1]).toFixed(1)+' ';st=true});
    g+=`<path d="${p}" fill="none" stroke="${COL[ki%4]}" stroke-width="1.4"/>`});
  document.getElementById(elId).innerHTML=`<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
  document.getElementById(legId).innerHTML=keys.map((k,i)=>
    `<span style="color:${COL[i%4]}">■ ${k}</span>`).join('');
}
const s1={};s1['KOSPI(log)']=D.series['KOSPI(log)'];s1['신용잔고(조원)']=D.series['신용잔고(조원)'];
s1['예탁금(조원)']=D.series['예탁금(조원)'];
chart('c1','l1',s1);
chart('c2','l2',D.ratio,{key:'신용융자/고객예탁금'});
chart('c3','l3',D.kosdaq_credit,{key:'신용융자_코스닥_12개월변화율'});

let MK='KOSPI';
const mkEl=document.getElementById('mk');
mkEl.innerHTML=['KOSPI','KOSDAQ'].map(m=>
  `<button data-m="${m}" style="background:${m===MK?'var(--b)':'transparent'};color:var(--ink);
   border:1px solid var(--line);border-radius:7px;padding:4px 12px;margin-right:6px;cursor:pointer">${m}</button>`).join('');
mkEl.onclick=e=>{if(!e.target.dataset.m)return;MK=e.target.dataset.m;
  [...mkEl.children].forEach(b=>b.style.background=b.dataset.m===MK?'var(--b)':'transparent');
  drawIC();drawTail();drawComp()};

function num(v,t){if(v===null||v===undefined)return '<td class="mut">—</td>';
  const cls=v<0?'neg':'pos';const s=(v>0?'+':'')+v.toFixed(3);
  return `<td class="${cls}">${s}<span class="mut" style="font-size:11px">(${t===null||t===undefined?'':(t>0?'+':'')+t})</span></td>`}
function drawIC(){
  const rows=D.markets[MK].ic;
  document.querySelector('#tic thead').innerHTML=
    '<tr><th>신호</th>'+HZ.map(h=>`<th>${h}</th>`).join('')+'</tr>';
  document.querySelector('#tic tbody').innerHTML=rows.map(r=>
    `<tr><td>${r.signal}</td>`+HZ.map(h=>num(r[h],r[h+'_t'])).join('')+'</tr>').join('');
}
function cell(c){if(!c)return '<td class="mut">—</td>';
  const[m,w]=c;return `<td class="${m<0?'neg':'pos'}">${m>0?'+':''}${m}% <span class="mut">${w}%</span></td>`}
function drawTail(){
  const t=D.markets[MK].tails;
  document.querySelector('#ttail thead').innerHTML=
    '<tr><th>신호 / 구간</th>'+HZ.map(h=>`<th>${h}</th>`).join('')+'</tr>';
  let h='';
  Object.entries(t).forEach(([name,v])=>{
    h+=`<tr><td colspan="6" style="color:var(--a);border-bottom:none;padding-top:12px">${name}</td></tr>`;
    [['하위 5% (극단바닥)','lo'],['전체평균','mid'],['상위 5% (극단과열)','hi']].forEach(([lb,k])=>{
      h+=`<tr><td style="padding-left:16px">${lb}</td>`+HZ.map(x=>cell(v[k][x])).join('')+'</tr>'})});
  document.querySelector('#ttail tbody').innerHTML=h;
}
function drawComp(){
  const c=D.markets[MK].composite;let h='';
  Object.entries(c).forEach(([lb,v])=>{
    if(!v.quantiles)return;
    const mx=Math.max(...v.quantiles.map(q=>Math.abs(q.ret)))||1;
    h+=`<div style="margin-bottom:16px"><div style="font-size:12.5px;margin-bottom:2px">
      <b class="st">${lb}</b> <span class="tag">구성: ${v.members.join(' · ')}</span></div>
      <div class="tag" style="margin-bottom:6px">현재 점수 ${v.current} · 역사적 ${v.current_pct} 백분위</div>`;
    v.quantiles.forEach(q=>{
      const w=Math.abs(q.ret)/mx*46;
      h+=`<div style="display:flex;align-items:center;gap:8px;font-size:12px;margin:2px 0">
        <span style="width:52px;color:var(--dim)">${q.q}분위</span>
        <span style="width:66px" class="${q.ret<0?'neg':'pos'}">${q.ret>0?'+':''}${q.ret}%</span>
        <span style="width:60px;color:var(--dim)">승률 ${q.win}%</span>
        <span class="bar" style="width:${w}%;background:${q.ret<0?'var(--d)':'var(--c)'}"></span>
        <span class="tag">n=${q.n}</span></div>`});
    h+='</div>'});
  document.getElementById('comp').innerHTML=h||'<div class="tag">표본 부족</div>';
}
drawIC();drawTail();drawComp();

document.querySelector('#tccf tbody').innerHTML=(D.ccf||[]).map(r=>
  `<tr><td>${r.signal}</td><td>${r.peak_lag}</td>
   <td class="${r.peak_corr<0?'neg':'pos'}">${r.peak_corr>0?'+':''}${r.peak_corr}</td>
   <td class="mut">±${r.conf}</td><td>${r.sig?'★':''}</td></tr>`).join('');

document.getElementById('pos').innerHTML=D.position.map(p=>
  `<div style="display:flex;align-items:center;gap:10px;font-size:12.5px;margin:3px 0">
    <span style="width:210px">${p.signal}</span>
    <span style="width:52px;text-align:right;color:${p.pct>90?'var(--d)':p.pct<10?'var(--c)':'var(--ink)'}">${p.pct}%</span>
    <span class="bar" style="width:${p.pct*0.62}%;background:${p.pct>90?'var(--d)':p.pct<10?'var(--c)':'var(--b)'}"></span>
  </div>`).join('');
</script>'''


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("fetch", "all"):
        build_funds_parquet()
    if cmd in ("analyze", "all"):
        analyze_and_render()
