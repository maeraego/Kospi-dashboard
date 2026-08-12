# -*- coding: utf-8 -*-
"""
collect_kofia.py — 금융투자협회 FreeSIS 증시자금/신용공여 수집기
사용법:  C:/python312/python.exe collect_kofia.py
출력:    kofia_daily.parquet

수집 항목 (일별, 원 단위):
  · 증시자금추이   STATSCU0100000060  (1998-06-18~)
      투자자예탁금 / 파생예수금 / RP잔고 / 위탁매매미수금 / 반대매매금액 / 반대매매비중
  · 신용공여 잔고  STATSCU0100000070  (1998-07-01~, 시장별은 2002-05-02~)
      신용융자 전체·유가증권·코스닥 / 대주 전체·유가·코스닥 / 청약자금대출 / 예탁증권담보융자

API 메모 (역공학 결과 — 문서 없음):
  POST /meta/getMetaDataList.do
  body {"dmSearch":{"tmpV1":주기(D/M), "tmpV45":시작YYYYMMDD, "tmpV46":종료,
                    "tmpV40":"1", "tmpV41":"1",   # ★ 이 둘이 없으면 값이 전부 null로 온다
                    "OBJ_NM":"<SERVICE_ID>BO"}}
  tmpV40/41 = 단위/소수점 지정. "1","1" 이면 원 단위 원본값.
  화면 정의(컬럼 이름·시작일)는 POST /meta/getSrvData.do 로 조회 가능.
"""
import json, time, sys
import urllib.request
import pandas as pd

BASE = "https://freesis.kofia.or.kr"
HDRS = {'Content-Type': 'application/json;charset=UTF-8',
        'User-Agent': 'Mozilla/5.0', 'Referer': BASE + '/'}

# SERVICE_ID -> (컬럼 매핑 TMPVn, 시작일)
SPECS = {
    "STATSCU0100000060": (
        {"TMPV2": "투자자예탁금", "TMPV3": "파생예수금", "TMPV4": "RP잔고",
         "TMPV5": "위탁매매미수금", "TMPV6": "반대매매금액", "TMPV7": "반대매매비중"},
        "19980618"),
    "STATSCU0100000070": (
        {"TMPV2": "신용융자", "TMPV3": "신용융자_유가", "TMPV4": "신용융자_코스닥",
         "TMPV5": "대주", "TMPV6": "대주_유가", "TMPV7": "대주_코스닥",
         "TMPV8": "청약자금대출", "TMPV9": "예탁증권담보융자"},
        "19980701"),
}


def _raw(service_id, start, end, retries=3):
    """한 번의 요청. 응답이 잘리면 예외."""
    body = {"dmSearch": {"tmpV1": "D", "tmpV45": start, "tmpV46": end,
                         "tmpV40": "1", "tmpV41": "1", "OBJ_NM": service_id + "BO"}}
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(BASE + "/meta/getMetaDataList.do",
                                         data=json.dumps(body).encode(), headers=HDRS)
            with urllib.request.urlopen(req, timeout=60) as r:
                buf = b"".join(iter(lambda: r.read(8192), b""))
            return json.loads(buf.decode("utf-8", "replace")).get("ds1") or []
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(str(last))


def fetch(service_id, start, end, depth=0):
    """서버 응답이 약 32KB에서 잘리는 버그가 있어, 실패하면 기간을 반으로 쪼개 재귀 수집."""
    try:
        return _raw(service_id, start, end)
    except Exception as e:
        s, t = pd.Timestamp(start), pd.Timestamp(end)
        if depth > 6 or (t - s).days < 5:
            raise RuntimeError(f"{service_id} {start}~{end}: {e}")
        mid = s + (t - s) / 2
        a = fetch(service_id, start, mid.strftime("%Y%m%d"), depth + 1)
        b = fetch(service_id, (mid + pd.Timedelta(days=1)).strftime("%Y%m%d"), end, depth + 1)
        return a + b


def collect(service_id, chunk_years=1):
    cols, first = SPECS[service_id]
    today = pd.Timestamp.today().strftime("%Y%m%d")
    frames = []
    y0, y1 = int(first[:4]), int(today[:4])
    for y in range(y0, y1 + 1, chunk_years):
        s = max(first, f"{y}0101")
        e = min(today, f"{min(y + chunk_years - 1, y1)}1231")
        rows = fetch(service_id, s, e)
        print(f"  · {service_id} {s}~{e}  n={len(rows)}")
        if rows:
            frames.append(pd.DataFrame(rows))
        time.sleep(0.4)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["TMPV1"], format="%Y%m%d")
    out = df[["date"] + [c for c in cols if c in df.columns]].rename(columns=cols)
    out = out.set_index("date").sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out.apply(pd.to_numeric, errors="coerce")


def main():
    print("[수집] 금융투자협회 FreeSIS")
    parts = []
    for sid in SPECS:
        d = collect(sid)
        if d is None:
            print(f"[경고] {sid} 수집 실패")
            continue
        parts.append(d)
    if not parts:
        print("[중단] 수집된 데이터 없음"); sys.exit(1)

    df = parts[0]
    for p in parts[1:]:
        df = df.join(p, how="outer")
    df.index.name = "date"

    # ── 파생 지표 ──
    # 억원 환산(가독성) 대신 원 단위 유지. 비율만 파생.
    if "신용융자" in df and "투자자예탁금" in df:
        df["신용_예탁금배율"] = df["신용융자"] / df["투자자예탁금"]
    if "신용융자" in df:
        df["신용_대주비"] = df["신용융자"] / df["대주"].replace(0, pd.NA)

    df.to_parquet("kofia_daily.parquet")
    print("\n" + "=" * 60)
    print(f"기간 : {df.index[0].date()} ~ {df.index[-1].date()}  ({len(df)} rows)")
    for c in df.columns:
        s = df[c].dropna()
        if len(s):
            print(f"  {c:16s} {s.index[0].date()} ~ {s.index[-1].date()}  n={len(s):5d}  최신={s.iloc[-1]:,.4g}")
    print("=" * 60)
    print("저장 완료 → kofia_daily.parquet")


if __name__ == "__main__":
    main()
