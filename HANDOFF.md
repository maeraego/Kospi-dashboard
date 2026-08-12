# HANDOFF — 증시주변자금 → KOSPI 예측 신호 대시보드 (Claude Code 자율 실행용)

## 목표
신용잔고·고객예탁금(및 미수금·선물예수금)을 **최장 일별**로 수집해, 코스피 지수와의
**선후상관·IC**를 계산하고, 다음 계열/비율을 다크 테마 단독 HTML 대시보드로 만든다.
1) 신용잔고  2) 고객예탁금  3) 코스피지수  4) 신용잔고/코스피  5) 신용잔고/예탁금
→ 각 신호가 코스피 **향후 수익률(5·20·60일)** 을 예측하는지 IC·CCF로 검증.

`funds_pipeline.py` 의 **분석·HTML 절반은 이미 완성·검증됨**. 네가 할 일은 **자동 수집**을
붙여 `funds.parquet` 를 만들고 파이프라인을 끝까지 돌리는 것.

## 환경 (Windows)
- 작업 폴더: `C:\Users\user\minyong-agent\Github`  (레포 `maeraego/Kospi-dashboard`)
- Python: `C:\python312\python.exe`
- 이미 있는 파일: `krx_daily.parquet`(`KOSPI_종가` 1995~ 일별), `.env`(`ECOS_KEY=...`)
- Git: push 전 항상 `git pull --no-edit`
- 산출물 규칙: CDN 의존 없는 단독 HTML(다크), CSV는 UTF-8 BOM

## 데이터 소스 (핵심)
FreeSIS(금융투자협회)가 네 계열 모두 일별 정본. WebSquare(JS) 앱이라 **브라우저로 XHR을
가로채는 방식**이 가장 확실하다. 확인된 페이지:
- 증시자금추이(예탁금·미수금·선물예수금): `serviceId=STATSCU0100000060`, `parentDivId=MSIS10000000000000`
- 신용공여잔고 추이(신용잔고): `serviceId=STATSCU0100000070`
- 진입 URL 예: `https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000060`

### 수집 전략 (probe → 자동)
1. **Playwright로 1회 인터셉트**해 실제 데이터 XHR(엔드포인트+페이로드+응답 필드명)을 알아낸다.
   - `pip install playwright && playwright install chromium`
   - 페이지 진입 → 조회기간을 최대(예: 2005-01-01~오늘)로 설정 → 조회 클릭
   - `page.on("response")`로 표 데이터가 담긴 응답(JSON/XML)을 잡아 본문·요청정보를 저장
2. 알아낸 엔드포인트/페이로드/필드명을 `funds_pipeline.py` 상단 `FREESIS` 딕셔너리에 기록
   (`url`, `headers`, `body_template`(날짜 자리 `{start}`/`{end}`), `json_path`/`xml_row_tag`,
   `date_key`, `value_key`). 이후 일일 갱신은 브라우저 없이 `requests`로 빠르게.
3. 만약 응답이 그리드 렌더뿐이고 XHR을 못 잡으면, DOM 그리드를 직접 스크레이프해 폴백.

### Playwright 인터셉트 시작 스켈레톤
```python
# freesis_probe.py  — 1회 실행해 엔드포인트/필드명 확인 후 FREESIS 딕셔너리에 반영
import json
from playwright.sync_api import sync_playwright

TARGETS = {
  "증시자금추이": "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000060",
  "신용공여잔고": "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070",
}
def probe(url):
    caught = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True); pg = b.new_page()
        def on_resp(r):
            ct = (r.headers.get("content-type") or "")
            if r.request.method == "POST" and ("json" in ct or "xml" in ct):
                try:
                    body = r.text()
                    if any(t in body for t in ("잔고","예탁","AMT","BAL","DD","일자")):
                        caught.append({"url": r.url, "req_headers": r.request.headers,
                                       "post_data": r.request.post_data, "sample": body[:1500]})
                except Exception: pass
        pg.on("response", on_resp)
        pg.goto(url, wait_until="networkidle", timeout=60000)
        # WebSquare 조회기간 확대 + 조회 클릭: 실제 셀렉터는 페이지에서 확인해 조정
        # 예) pg.fill("#startDd_input","20050101"); pg.click("#searchBtn"); pg.wait_for_timeout(4000)
        pg.wait_for_timeout(6000)
        b.close()
    return caught
if __name__ == "__main__":
    out = {k: probe(u) for k, u in TARGETS.items()}
    json.dump(out, open("freesis_probe.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)
    print("saved freesis_probe.json — url/post_data/필드명 확인 후 FREESIS 딕셔너리에 반영")
```
- 셀렉터(조회버튼/기간입력 id)는 페이지에서 직접 확인해 채운다. 못 잡으면 `headless=False`로 눈으로 보며 조정.
- `sample` 본문에서 날짜 필드명(예: `TRD_DD`/`BAS_DD`)과 값 필드명(신용잔고·예탁금)을 확정해 `funds_pipeline.py`에 반영.

### ECOS 보조 (예탁금 교차검증, 선택)
`.env`의 `ECOS_KEY`로 `collect_ecos.py`의 이름매칭 방식 재사용해 투자자예탁금 존재 시 교차검증.
없거나 주기가 안 맞으면 FreeSIS를 정본으로.

## 파이프라인 실행
```
C:\python312\python.exe freesis_probe.py           # 1회: 엔드포인트/필드명 확인
# → funds_pipeline.py 상단 FREESIS 딕셔너리 채우기
C:\python312\python.exe funds_pipeline.py all      # fetch → 분석 → HTML
```
`funds_pipeline.py`가 자동 계산: 신용잔고/코스피, 신용잔고/예탁금, 각 신호의 IC(5·20·60일),
pre-whitened CCF 선후상관(peak_lag>0 = 자금이 코스피 선행), `fund_signal_dashboard.html` 생성.

## 완료 기준 (acceptance)
- [ ] `funds.parquet`에 신용잔고·예탁금 일별, 시작일 최소 2010 이전(가능하면 2005~), 결측 최소
- [ ] `fund_signal_dashboard.html` 생성: 4계열 추이 + IC표 + CCF표, CDN 의존 없음, 다크
- [ ] IC/CCF 수치가 **실데이터** 기반(임시·합성 금지). 부호가 경제적 직관과 대조 가능해야
- [ ] 선후상관 해석 1~2줄: 어떤 자금 신호가 코스피를 선행/후행하며 |IC|가 유의한지
- [ ] `git pull --no-edit && git add && git commit && git push`로 반영, GitHub Pages 확인

## 주의
- 룩어헤드 금지: FreeSIS 자금은 T+1 공표 → 시그널은 t+1부터 유효. fwd수익률은 미래 shift로 OK.
- 신용잔고 정규화는 **레벨 비율(신용잔고/코스피 등)** 로만; 원계열 로그차분을 시총으로 나눈 뒤
  차분하면 -코스피수익률이 기계적으로 주입돼 허위 -상관 발생(이미 pipeline이 원계열 차분 사용).
- FreeSIS 이용약관(참고용·재배포 제한) 준수, 과도한 요청 자제(기간 넓게 1~2회 호출).
