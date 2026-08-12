# -*- coding: utf-8 -*-
"""
collect_vkospi.py — VKOSPI (코스피200 변동성지수) 수집기
사용법:  C:/python312/python.exe collect_vkospi.py          (증분)
         C:/python312/python.exe collect_vkospi.py --full   (전체 재수집 2003~)
출력:    vkospi_daily.parquet   (종가·시가·고가·저가)

왜 이 방식인가
--------------
VKOSPI는 파생상품 지수라 pykrx가 노출하지 않는다(지수 목록 168개에 없음).
KRX가 2025년 말부터 MDC 통계를 로그인 뒤로 옮겨 비인증 호출은 400을 받는다.
그래서 collect_krx.py가 이미 쓰는 pykrx 인증 세션(.env의 KRX_ID/KRX_PW로 로그인)을
그대로 재사용해 MDC의 JSON 엔드포인트를 직접 호출한다.

  화면 : [11012] 개별지수 시세 추이  (통계 > 기본통계 > 지수 > 파생 및 기타지수)
  POST  https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd
  bld   dbms/MDC/STAT/standard/MDCSTAT01201
  지수  indTpCd=1, idxIndCd=300, idxCd=1, idxCd2=300  (코스피 200 변동성지수)
  기간  strtDd / endDd (YYYYMMDD)

  ※ 조회 구간이 2년을 넘으면 INVALIDPERIOD2 를 돌려준다 → 2년씩 끊어서 요청.
  ※ 데이터는 2003-01-02부터 있다(기준시점). 공식 발표시점은 2009-04-13이므로
    2003~2009 구간은 KRX가 소급 산출한 값이다.

VKOSPI vs 실현변동성
--------------------
build_dashboard.py 의 '실현변동성(20일)'은 코스피 일간 등락폭에서 만든 실현변동성이고,
VKOSPI는 코스피200 옵션 가격에서 뽑은 향후 30일 기대변동성(내재변동성)이다.
전자는 이미 일어난 등락, 후자는 앞으로 예상되는 등락을 재므로 급락 직후엔 크게 벌어진다.
"""
import os, sys, time
import pandas as pd

OUT = "vkospi_daily.parquet"
URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
BLD = "dbms/MDC/STAT/standard/MDCSTAT01201"
IDX = {"indTpCd": "1", "idxIndCd": "300", "idxCd": "1", "idxCd2": "300"}
FIRST = "20030102"
HDRS = {"User-Agent": "Mozilla/5.0",
        "Referer": "https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
        "X-Requested-With": "XMLHttpRequest"}
COLS = {"CLSPRC_IDX": "VKOSPI", "OPNPRC_IDX": "VKOSPI_시가",
        "HGPRC_IDX": "VKOSPI_고가", "LWPRC_IDX": "VKOSPI_저가"}


def krx_session():
    """collect_krx.py 와 같은 경로로 로그인한 pykrx 세션을 얻는다."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    if not os.environ.get("KRX_ID"):
        print("[중단] .env 에 KRX_ID / KRX_PW 가 필요합니다 (KRX가 로그인을 요구함).")
        sys.exit(1)
    from pykrx import stock
    stock.get_index_ticker_name("1001")           # 로그인 트리거
    from pykrx.website.comm import auth
    s = auth._auth_session
    if s is None or not s.is_authenticated:
        print("[중단] KRX 로그인 실패."); sys.exit(1)
    return s.session


def fetch(sess, start, end, retries=3):
    p = {"bld": BLD, "locale": "ko_KR", **IDX,
         "strtDd": start, "endDd": end, "csvxls_isNo": "false"}
    last = None
    for i in range(retries):
        try:
            r = sess.post(URL, data=p, headers=HDRS, timeout=60)
            return r.json().get("output", [])
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{start}~{end}: {last}")


def to_frame(rows):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["TRD_DD"], format="%Y/%m/%d")
    out = df[["date"] + [c for c in COLS if c in df.columns]].rename(columns=COLS)
    out = out.set_index("date").sort_index()
    out = out[~out.index.duplicated(keep="last")]
    for c in out.columns:
        out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", ""), errors="coerce")
    return out


def collect_range(sess, start, end):
    """2년 초과 구간은 INVALIDPERIOD2 가 나므로 2년씩 끊어 모은다."""
    frames = []
    s = pd.Timestamp(start)
    fin = pd.Timestamp(end)
    while s <= fin:
        e = min(s + pd.DateOffset(years=2) - pd.Timedelta(days=1), fin)
        rows = fetch(sess, s.strftime("%Y%m%d"), e.strftime("%Y%m%d"))
        print(f"  · {s.date()} ~ {e.date()}  n={len(rows)}")
        f = to_frame(rows)
        if f is not None:
            frames.append(f)
        s = e + pd.Timedelta(days=1)
        time.sleep(0.4)
    if not frames:
        return None
    df = pd.concat(frames)
    return df[~df.index.duplicated(keep="last")].sort_index()


def main():
    full = "--full" in sys.argv
    prev = None
    if not full and os.path.exists(OUT):
        try:
            prev = pd.read_parquet(OUT)
        except Exception as e:
            print(f"[경고] 기존 {OUT} 읽기 실패 → 전체 수집: {e}")

    sess = krx_session()
    today = pd.Timestamp.today().strftime("%Y%m%d")

    if prev is not None and len(prev):
        # 증분: 마지막 날짜 −14일부터(지수 정정 흡수)
        start = (prev.index.max() - pd.Timedelta(days=14)).strftime("%Y%m%d")
        print(f"[수집] VKOSPI (증분 {start}~{today})")
        new = collect_range(sess, start, today)
        if new is None:
            print("[정보] 새 데이터 없음 - 기존 파일 유지"); return
        df = pd.concat([prev, new])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        print(f"  → 기존 {len(prev)}행 + 신규 {max(len(df)-len(prev),0)}행 = {len(df)}행")
    else:
        print(f"[수집] VKOSPI (전체 {FIRST}~{today})")
        df = collect_range(sess, FIRST, today)
        if df is None:
            print("[중단] 수집 실패"); sys.exit(1)

    df.index.name = "date"
    df.to_parquet(OUT)
    print("\n" + "=" * 56)
    print(f"기간 : {df.index[0].date()} ~ {df.index[-1].date()}  ({len(df)} rows)")
    s = df["VKOSPI"].dropna()
    print(f"VKOSPI  최신 {s.iloc[-1]:.2f}  최소 {s.min():.2f}  최대 {s.max():.2f}  평균 {s.mean():.2f}")
    print("=" * 56)
    print(f"저장 완료 → {OUT}")


if __name__ == "__main__":
    main()
