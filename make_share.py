# -*- coding: utf-8 -*-
"""
make_share.py — 보내기 좋은 대시보드 파일 한 장 만들기
사용법:  C:/python312/python.exe make_share.py

왜 필요한가
-----------
대시보드를 GitHub Pages로 공개하지 않고 '보고 싶은 사람에게만 파일로 전달'하는 방식이라,
카톡·메일에 바로 얹을 수 있는 파일이 매일 한 장 준비돼 있어야 한다.

하는 일
-------
  1. dashboard.html 을 share/ 폴더에 날짜 붙여 복사
       share/코스피대시보드_20260812.html
  2. share/최신.html 로도 복사 (링크를 고정해두고 싶을 때 · 클라우드 동기화 폴더용)
  3. 오래된 파일 정리 (기본 30개 보관)

대시보드는 CDN 의존이 없는 단독 HTML이라 받는 사람은 더블클릭만 하면 열린다.
인터넷 연결도, 계정도 필요 없다.
"""
import os, re, shutil, sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "dashboard.html")
SHARE = os.path.join(HERE, "share")
KEEP = 30
PREFIX = "코스피대시보드_"


def main():
    if not os.path.exists(SRC):
        print(f"[중단] {SRC} 가 없습니다. build_dashboard.py 를 먼저 실행하세요.")
        sys.exit(1)

    os.makedirs(SHARE, exist_ok=True)
    # 파일 자체의 생성 시각을 쓴다(자정 넘어 실행돼도 그날 데이터로 이름이 붙게)
    stamp = datetime.fromtimestamp(os.path.getmtime(SRC)).strftime("%Y%m%d")
    dated = os.path.join(SHARE, f"{PREFIX}{stamp}.html")
    latest = os.path.join(SHARE, "최신.html")

    shutil.copy2(SRC, dated)
    shutil.copy2(SRC, latest)
    size = os.path.getsize(dated) / 1024

    # 오래된 것 정리
    files = sorted(
        (f for f in os.listdir(SHARE) if re.fullmatch(PREFIX + r"\d{8}\.html", f)),
        reverse=True)
    for f in files[KEEP:]:
        try:
            os.remove(os.path.join(SHARE, f))
        except Exception:
            pass

    print(f"[공유파일] {dated}  ({size:,.0f} KB)")
    print(f"[공유파일] {latest}")
    print(f"           보관 {min(len(files), KEEP)}개 (최대 {KEEP}개)")
    print(f"           이 파일을 카톡·메일로 보내면 받는 사람이 더블클릭으로 엽니다.")


if __name__ == "__main__":
    main()
