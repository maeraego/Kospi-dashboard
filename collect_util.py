# -*- coding: utf-8 -*-
"""
collect_util.py  —  수집기 공용 저장 유틸

왜 있나 (2026-11-03 사고):
  수집은 지표별로 독립 실패하는데 저장은 한 덩어리였다. ECOS 가
  StatisticItemList 에 일시적으로 빈 응답을 줘서 CD91 하나가 안 잡혔는데,
  `to_parquet` 이 파일을 통째로 덮어써 **31년 이력이 같이 사라졌다**
  (ecos_monthly.parquet 48,908 -> 46,868 바이트).
  그 결과 season_dashboard.py 의 e['CD91'] 이 KeyError 로 죽어
  클라우드 빌드(Actions #212)가 실패했다.

  수집기마다 같은 구조라 어디서든 재발할 수 있었다. 저장을 한 곳으로 모아
  '못 받은 것은 지난 값을 유지한다'를 기본값으로 만든다.

쓰는 법:
    from collect_util import merge_save
    daily = merge_save(daily, "fred_daily.parquet")

주의 — 이 함수가 하지 않는 일:
  원천이 값을 '의도적으로 지운' 경우(정상 공표 후 철회)까지 구분하지 못한다.
  지운 값이 지난 값으로 남는다. 금리·주가·환율에는 사실상 없는 패턴이고,
  31년 이력을 잃는 쪽이 훨씬 나쁘므로 이 교환을 택한다.
  컬럼이 이렇게 유지되면 경고를 찍으니 로그에서 원인을 확인해야 한다.
"""
import os
import pandas as pd

__all__ = ["merge_save"]


def merge_save(new, path, label=None, quiet=False):
    """새로 수집한 프레임을 기존 parquet 과 병합해 저장하고, 병합 결과를 돌려준다.

    규칙:
      · 새 값이 있는 자리는 **항상 새 값이 이긴다** (갱신·정정이 반영된다).
      · 기존 파일은 새 수집이 **비워둔 자리만** 메운다.
        -> 못 받은 지표는 지난 값 유지, 받은 지표는 최신으로 갱신.
      · 컬럼 순서는 새 프레임 기준을 유지하고, 이번에 빠진 컬럼은 뒤에 붙인다
        (combine_first 는 컬럼을 알파벳순으로 재배열해 버린다).
      · 이번 수집에서 빠진 컬럼이 있으면 경고를 찍는다.

    path 가 없거나 읽을 수 없으면 새 프레임을 그대로 쓴다.
    """
    name = label or os.path.basename(path)
    if not os.path.exists(path):
        new.to_parquet(path)
        return new
    try:
        old = pd.read_parquet(path)
    except Exception as e:
        if not quiet:
            print(f"  ! 기존 {name} 를 읽을 수 없어 새로 씁니다: {e}")
        new.to_parquet(path)
        return new

    lost = [c for c in old.columns if c not in set(new.columns)]
    out = new.combine_first(old)
    # 컬럼 순서 복원 (combine_first 가 알파벳순으로 흐트러뜨린다)
    out = out[list(new.columns) + lost]
    out.index.name = new.index.name or old.index.name

    if lost and not quiet:
        print(f"  ! {name}: 이번 수집에서 빠진 컬럼 {lost}"
              f" — 기존 이력을 유지합니다 (위 수집 로그에서 원인 확인 필요)")
    gained = len(out) - len(old)
    if gained and not quiet:
        print(f"  · {name}: {len(old)} -> {len(out)} 행 (+{gained}), {len(out.columns)}열")
    out.to_parquet(path)
    return out
