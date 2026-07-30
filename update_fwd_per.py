# -*- coding: utf-8 -*-
"""
update_fwd_per.py  —  예상PER(Forward PER) 갱신 도구

무료 자동 소스가 없어 월 1회 수동 입력한다. 세 가지 방식 지원:

  1) 대화형 (가장 간단)   : C:/python312/python.exe update_fwd_per.py
  2) 값 직접 지정         : ... update_fwd_per.py 7.4
     특정 월 지정          : ... update_fwd_per.py 7.4 2026-08
  3) CSV 일괄 반영        : ... update_fwd_per.py --csv fwd_per.csv
     (CSV 형식: 첫 열 날짜(YYYY-MM), 둘째 열 예상PER. 헤더 있어도 됨)

값을 어디서 보나:
  - 본인 엑셀/차트의 '예상PER' 최신값
  - 증권사 HTS/MTS 시장지표 화면의 코스피 12개월 선행 PER
  - 네이버금융·언론 기사에 인용되는 '코스피 12개월 선행 PER'

기존 이력(이미지 복원본)은 그대로 두고 새 월만 덧붙이거나 덮어쓴다.
출력: fwd_per_monthly.parquet
"""
import os, sys
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, 'fwd_per_monthly.parquet')
COL  = '예상PER'

def load():
    if os.path.exists(PATH):
        s = pd.read_parquet(PATH)[COL]
        s.index = pd.to_datetime(s.index)
        return s.sort_index()
    print("[안내] 기존 파일이 없어 새로 만듭니다.")
    return pd.Series(dtype=float, name=COL)

def save(s):
    s = s.sort_index()
    s.index.name = 'date'
    s.to_frame(COL).to_parquet(PATH)
    print(f"\n저장 완료 → fwd_per_monthly.parquet  (총 {len(s)}개월, "
          f"{s.index[0].date()} ~ {s.index[-1].date()})")
    print(f"  최근 6개월:\n{s.tail(6).round(2).to_string()}")
    print("\n다음 단계:  C:/python312/python.exe build_dashboard.py")

def month_end(txt):
    return pd.Timestamp(txt if len(txt) > 7 else txt + '-01') + pd.offsets.MonthEnd(0)

def put(s, when, val):
    ts = month_end(when)
    old = s.get(ts)
    s.loc[ts] = float(val)
    tag = f"(기존 {old:.2f} → 덮어씀)" if old == old and old is not None else "(신규)"
    print(f"  · {ts.date()}  예상PER = {float(val):.2f}  {tag}")
    return s

def eps_mode(eps):
    """예상EPS를 받아, 코스피 지수로 선행PER을 '매달 자동 계산'해 채운다.

    선행PER = 지수 / 예상EPS 이므로, 지수는 이미 자동수집되고 있어
    바뀌지 않는 예상EPS만 가끔 갱신하면 된다. 매일 손으로 넣을 필요가 없다.
    """
    kp = os.path.join(HERE, 'krx_monthly.parquet')
    if not os.path.exists(kp):
        print("[오류] krx_monthly.parquet 이 없습니다. 먼저 데이터를 수집하세요.")
        sys.exit(1)
    px = pd.read_parquet(kp)['KOSPI_종가'].dropna()
    epsf = os.path.join(HERE, 'fwd_eps.csv')

    # 기존 EPS 이력 읽고, 이번 값을 이번 달로 기록
    hist = pd.Series(dtype=float)
    if os.path.exists(epsf):
        try:
            _h = pd.read_csv(epsf)
            hist = pd.Series(_h.iloc[:, 1].values,
                             index=pd.to_datetime(_h.iloc[:, 0])).sort_index()
        except Exception:
            pass
    now_m = px.index[-1]
    hist.loc[now_m] = float(eps)
    hist = hist.sort_index()
    hist.to_frame('예상EPS').rename_axis('날짜').to_csv(epsf)

    # EPS를 각 시점으로 전방채움 → 지수와 나눠 선행PER 산출
    eps_series = hist.reindex(px.index.union(hist.index)).ffill().reindex(px.index)
    per = (px / eps_series).dropna()
    per.name = COL

    old = load()
    merged = per.combine_first(old).sort_index() if len(old) else per
    save(merged)
    print(f"\nEPS 모드: 예상EPS {float(eps):,.0f} 기록 ({now_m.date()})")
    print(f"  → 선행PER = 지수 / EPS 로 자동 계산됩니다.")
    print(f"  최근: 지수 {px.iloc[-1]:,.0f} / EPS {eps_series.iloc[-1]:,.0f}"
          f" = {per.iloc[-1]:.2f}")
    print(f"  EPS 이력은 fwd_eps.csv 에 저장 (총 {len(hist)}건)")
    print("\n  다음부터는 지수가 바뀌어도 자동 반영되니, EPS가 바뀔 때만 다시 실행하세요.")


def ni_mode(fy1, fy2=None):
    """예상순이익(조원)으로 12개월 선행PER을 자동 계산한다.  ★권장 방식★

        12M Forward 순이익 = (a/12 × FY1) + ((12-a)/12 × FY2)
              a = 해당 회계연도(12월 결산)의 남은 개월수
        선행PER = 시가총액 / 12M Forward 순이익

    이 가중평균은 FnGuide가 12M Forward EPS를 만드는 방식과 동일하다.
    FY1(올해)·FY2(내년) 두 숫자만 넣으면
      · 시가총액은 KRX가 매일 자동 수집하므로 지수 변동이 즉시 반영되고
      · 월이 바뀔 때마다 FY1:FY2 비중이 저절로 굴러간다
    → 컨센서스가 바뀔 때만 다시 넣으면 된다.

    FY2를 생략하면 단일 추정치를 그대로 쓴다.
    """
    kp = os.path.join(HERE, 'krx_monthly.parquet')
    if not os.path.exists(kp):
        print("[오류] krx_monthly.parquet 이 없습니다. 먼저 데이터를 수집하세요.")
        sys.exit(1)
    mc = pd.read_parquet(kp)['KOSPI_시총'].dropna()      # 월말 시가총액(조원)
    # ── 오늘 시가총액을 일별 데이터에서 가져와 최신 월에 덮어쓴다 ──
    #   월별 parquet의 마지막 행은 '지난 월말' 값이라, 그대로 쓰면 선행PER이
    #   한 달에 한 번만 바뀐다. 일별 parquet의 최신 거래일 시총을 이번 달에 반영해
    #   지수가 움직일 때마다(매일) 선행PER이 갱신되게 한다.
    dp = os.path.join(HERE, 'krx_daily.parquet')
    if os.path.exists(dp):
        try:
            _mcd = pd.read_parquet(dp)['KOSPI_시총'].replace(0, float('nan')).dropna()
            if len(_mcd):
                _last = _mcd.index[-1]                       # 최신 거래일
                _mkey = _last.to_period('M').to_timestamp('M')  # 그 달의 월말 타임스탬프
                mc.loc[_mkey] = float(_mcd.iloc[-1])         # 최신 시총으로 이번 달 갱신
                mc = mc.sort_index()
                print(f"  (오늘 시총 반영: {_last.date()} = {float(_mcd.iloc[-1]):,.0f}조)")
        except Exception as _e:
            print(f"  (일별 시총 반영 실패, 월별 사용: {_e})")

    fy1 = float(fy1)
    fy2 = float(fy2) if fy2 is not None else None

    nf = os.path.join(HERE, 'fwd_ni.csv')
    hist = pd.DataFrame(columns=['FY1', 'FY2'])
    if os.path.exists(nf):
        try:
            _h = pd.read_csv(nf, index_col=0, parse_dates=True)
            hist = _h[['FY1', 'FY2']]
        except Exception:
            pass
    asof = mc.index[-1]
    hist.loc[asof] = [fy1, fy2 if fy2 is not None else fy1]
    hist = hist.sort_index()
    hist.rename_axis('날짜').to_csv(nf)

    # 각 월말 시점의 FY1/FY2 추정치를 전방채움
    h = hist.reindex(mc.index.union(hist.index)).ffill().reindex(mc.index)
    a = 12 - mc.index.month                    # 남은 개월수 (12월결산 기준)
    blend = (a / 12) * h['FY1'] + ((12 - a) / 12) * h['FY2']
    # 예상순이익 시계열에도 최신값을 이어붙인다(차트 추출 이력과 연속되게)
    _nip = os.path.join(HERE, 'fwd_ni_monthly.parquet')
    try:
        _ni = pd.read_parquet(_nip)['예상순이익']
        _ni.loc[asof] = float(blend.loc[asof])
        _ni.sort_index().to_frame().to_parquet(_nip)
        print(f"  (예상순이익 시계열에 {asof.date()} = {float(blend.loc[asof]):,.0f}조 기록)")
    except Exception:
        pass
    per = (mc / blend).dropna()
    per.name = COL

    old = load()
    merged = per.combine_first(old).sort_index() if len(old) else per
    save(merged)

    a_now = 12 - asof.month
    b_now = (a_now / 12) * fy1 + ((12 - a_now) / 12) * (fy2 if fy2 is not None else fy1)
    print(f"\n순이익 모드 ({asof.date()} 기준)")
    if fy2 is not None:
        print(f"  FY1(올해) {fy1:,.0f}조 × {a_now}/12  +  FY2(내년) {fy2:,.0f}조 × {12-a_now}/12")
        print(f"     =  12개월 선행 순이익 {b_now:,.0f}조")
    else:
        print(f"  예상순이익 {fy1:,.0f}조 (단일 추정치)")
    print(f"  시가총액 {mc.iloc[-1]:,.0f}조 (KRX 자동수집) / {b_now:,.0f}조"
          f"  =  선행PER {per.iloc[-1]:.2f}")
    print(f"\n  · 지수가 움직이면 시총이 바뀌어 선행PER이 매일 자동 갱신됩니다.")
    if fy2 is not None:
        nxt = 12 - (asof.month % 12 + 1)
        print(f"  · 다음 달에는 비중이 {nxt}/12 : {12-nxt}/12 로 저절로 굴러갑니다.")
    print(f"  · 컨센서스가 바뀔 때만 다시 실행하세요.  (이력: fwd_ni.csv)")


def _sanity(s):
    """입력한 선행PER이 함의하는 예상순이익을 보여준다(FnGuide 등과 대조용)."""
    try:
        mc = pd.read_parquet(os.path.join(HERE, 'krx_monthly.parquet'))['KOSPI_시총'].dropna()
        both = s.dropna().index.intersection(mc.index)
        if not len(both): return
        d = both[-1]
        print(f"\n  참고: 이 값은 12개월 선행 순이익 {mc[d] / s[d]:,.0f}조 를 함의합니다.")
        print(f"        (시가총액 {mc[d]:,.0f}조 기준 / {d.date()})")
        print(f"        FnGuide 등의 컨센서스와 맞는지 대조해 보세요.")
    except Exception:
        pass


def anchor_mode(args):
    """실제로 보도·공표된 선행PER 값(앵커)들로 과거 시계열 전체를 복원한다.

        선행PER = 시가총액 / 12개월 예상순이익

    시총은 KRX 실측이라 정확하고, 예상순이익은 컨센서스라 완만하게 움직인다.
    따라서 앵커 시점에서 순이익을 역산 → 그 사이를 로그선형 보간 → 모든 달에
    '정확한 시총 ÷ 추정 순이익'으로 선행PER을 다시 계산한다.
    PER의 급등락은 대부분 가격 때문이므로, 이 방식이 차트 디지타이즈보다 정확하다.

    사용:  --anchor 2020-03 7.77        (앵커 하나 추가)
           --anchor rebuild             (앵커만으로 전체 재구성)
           --anchor list                (등록된 앵커 보기)
    """
    af = os.path.join(HERE, 'fwd_anchors.csv')
    A = pd.Series(dtype=float)
    if os.path.exists(af):
        try:
            _a = pd.read_csv(af)
            A = pd.Series(_a.iloc[:, 1].values,
                          index=pd.to_datetime(_a.iloc[:, 0])).sort_index()
        except Exception:
            pass

    if args and args[0] == 'list':
        if not len(A):
            print("등록된 앵커가 없습니다."); return
        print(f"등록된 앵커 {len(A)}개:")
        for d, v in A.items():
            print(f"  {d.date()}  선행PER {v:.2f}")
        return

    if args and args[0] != 'rebuild':
        if len(args) < 2:
            print("[오류] 사용법:  --anchor 2020-03 7.77"); sys.exit(1)
        try:
            when = month_end(args[0]); val = float(args[1])
        except Exception:
            print(f"[오류] 형식이 잘못됐습니다: {' '.join(args[:2])}"); sys.exit(1)
        A.loc[when] = val
        A = A.sort_index()
        A.to_frame('선행PER').rename_axis('날짜').to_csv(af)
        print(f"앵커 등록: {when.date()}  선행PER {val:.2f}  (총 {len(A)}개)")

    if len(A) < 2:
        print("[중단] 앵커가 2개 이상이어야 복원할 수 있습니다.")
        print("       예:  --anchor 2020-03 7.77   /   --anchor 2020-08 12.84")
        return

    kp = os.path.join(HERE, 'krx_monthly.parquet')
    if not os.path.exists(kp):
        print("[오류] krx_monthly.parquet 이 없습니다."); sys.exit(1)
    mc = pd.read_parquet(kp)['KOSPI_시총'].dropna()

    # 앵커에서 순이익 역산 → 로그선형 보간(성장 시계열이므로) → 앞뒤는 최근값 유지
    ni_pts = {}
    for d, per in A.items():
        v = mc[mc.index <= d]
        if len(v) and per > 0:
            ni_pts[v.index[-1]] = float(v.iloc[-1]) / per
    if len(ni_pts) < 2:
        print("[중단] 시총과 겹치는 앵커가 2개 미만입니다."); return

    ni = pd.Series(ni_pts).sort_index()
    full = ni.reindex(mc.index.union(ni.index)).astype(float)
    full = np.exp(np.log(full).interpolate(method='time')).ffill().bfill()
    per_all = (mc / full.reindex(mc.index)).dropna()
    per_all.name = COL

    old = load()
    merged = per_all.combine_first(old).sort_index() if len(old) else per_all
    save(merged)

    print(f"\n앵커 {len(ni)}개로 {per_all.index[0].date()} ~ {per_all.index[-1].date()} 복원")
    print(f"  (시총 실측 ÷ 순이익 보간)")
    print("\n  앵커 재현 확인:")
    for d, per in A.items():
        v = per_all[per_all.index <= d]
        if len(v):
            print(f"    {d.date()}  목표 {per:6.2f}  복원 {float(v.iloc[-1]):6.2f}")


def rebuild_from_ni():
    """예상순이익 시계열(fwd_ni_monthly.parquet)과 KRX 시가총액으로 선행PER 전체를 재계산.

        선행PER = 시가총액 / 예상순이익

    예상순이익은 컨센서스라 완만하게 움직이고, 시가총액은 KRX가 매일 실측한다.
    따라서 지수가 변하면 선행PER이 저절로 따라간다.
    """
    nip = os.path.join(HERE, 'fwd_ni_monthly.parquet')
    kp = os.path.join(HERE, 'krx_monthly.parquet')
    if not os.path.exists(nip):
        print("[오류] fwd_ni_monthly.parquet 이 없습니다."); sys.exit(1)
    if not os.path.exists(kp):
        print("[오류] krx_monthly.parquet 이 없습니다."); sys.exit(1)

    ni = pd.read_parquet(nip)['예상순이익'].dropna()
    mc = pd.read_parquet(kp)['KOSPI_시총'].dropna()
    idx = mc.index.union(ni.index)
    ni_f = ni.reindex(idx).interpolate(method='time').ffill()
    per = (mc / ni_f.reindex(mc.index)).dropna()
    per.name = COL
    # 시가총액이 없는 과거 구간(예: KRX 2005년 이전)은 기존 값을 보존한다.
    # KRX를 1995년부터 다시 수집하면 그 구간도 이 방식으로 자동 대체된다.
    old_s = load()
    merged = per.combine_first(old_s).sort_index() if len(old_s) else per.sort_index()
    save(merged)
    print(f"\n예상순이익 {len(ni)}개월 × 시가총액 → 선행PER {len(per)}개월 재계산")
    print(f"  재계산 구간: {per.index[0].date()} ~ {per.index[-1].date()}"
          f"  (범위 {per.min():.2f}~{per.max():.2f})")
    if len(merged) > len(per):
        print(f"  이전 값 보존: {merged.index[0].date()} ~ (총 {len(merged)}개월)")
    print(f"  최근: 시총 {mc.iloc[-1]:,.0f}조 / 예상순이익 {ni_f.reindex(mc.index).iloc[-1]:,.0f}조"
          f" = {per.iloc[-1]:.2f}")
    return merged


def main():
    args = [a for a in sys.argv[1:]]

    # --rebuild : 예상순이익 시계열로 선행PER 전체 재계산
    if args and args[0] in ('--rebuild', '-r'):
        rebuild_from_ni()
        return

    # --anchor 모드: 실제 보도된 선행PER 값으로 과거 복원
    if args and args[0] in ('--anchor', '-a'):
        anchor_mode(args[1:])
        return

    # --ni 모드 (권장): 예상순이익(조원). FY1 FY2 두 개면 12개월 가중평균.
    if args and args[0] in ('--ni', '-n'):
        if len(args) < 2:
            print("[오류] 예상순이익을 조원 단위로 지정하세요.")
            print("        올해·내년 둘 다:  --ni 956 899   (권장, 12개월 가중평균)")
            print("        하나만:          --ni 899")
            sys.exit(1)
        try:
            ni_mode(args[1], args[2] if len(args) > 2 else None)
        except ValueError:
            print(f"[오류] 숫자가 아닙니다: {' '.join(args[1:])}"); sys.exit(1)
        return

    # --eps 모드: 예상EPS 절대값 입력
    if args and args[0] in ('--eps', '-e'):
        if len(args) < 2:
            print("[오류] 예상EPS 값을 지정하세요:  --eps 890"); sys.exit(1)
        try:
            eps_mode(float(args[1]))
        except ValueError:
            print(f"[오류] 숫자가 아닙니다: {args[1]}"); sys.exit(1)
        return

    s = load()

    # --csv 일괄
    if args and args[0] in ('--csv', '-c'):
        if len(args) < 2:
            print("[오류] CSV 경로를 지정하세요:  --csv fwd_per.csv"); sys.exit(1)
        path = args[1] if os.path.isabs(args[1]) else os.path.join(HERE, args[1])
        if not os.path.exists(path):
            print(f"[오류] 파일 없음: {path}"); sys.exit(1)
        df = pd.read_csv(path, header=None)
        # 헤더 행이면 건너뜀
        try: float(df.iloc[0, 1])
        except (ValueError, TypeError): df = df.iloc[1:]
        n = 0
        for _, r in df.iterrows():
            try:
                s = put(s, str(r.iloc[0]).strip(), float(r.iloc[1])); n += 1
            except Exception:
                continue
        print(f"\n{n}개 반영")
        save(s); return

    # 인자로 값 전달
    if args:
        val = args[0]
        when = args[1] if len(args) > 1 else pd.Timestamp.today().strftime('%Y-%m')
        try: float(val)
        except ValueError:
            print(f"[오류] 숫자가 아닙니다: {val}"); sys.exit(1)
        s = put(s, when, val); save(s); _sanity(s); return

    # 대화형
    if len(s):
        print(f"현재 최신: {s.index[-1].date()}  예상PER = {s.iloc[-1]:.2f}")
    cur = pd.Timestamp.today().strftime('%Y-%m')
    when = input(f"어느 달입니까? (엔터=이번 달 {cur}): ").strip() or cur
    val = input("예상PER 값 (예: 7.4): ").strip()
    if not val:
        print("[취소] 값이 입력되지 않았습니다."); return
    try: float(val)
    except ValueError:
        print(f"[오류] 숫자가 아닙니다: {val}"); return
    s = put(s, when, val); save(s); _sanity(s)

if __name__ == '__main__':
    main()
