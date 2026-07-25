# 핸드폰에서 계속 작업하기 — GitHub 이전 가이드

집 PC 없이도 대시보드가 알아서 갱신되고, 핸드폰으로 보고 고칠 수 있게 만듭니다.
**한 번만 세팅하면 그 뒤론 핸드폰만으로 됩니다.**

---

## 무엇이 달라지나

| | 지금 | 이후 |
|---|---|---|
| 데이터 갱신 | 집 PC 켜고 직접 실행 | 클라우드가 평일 18:30 자동 |
| 대시보드 보기 | 집 PC의 HTML 파일 | 인터넷 주소 (핸드폰 브라우저) |
| 코드 수정 | 파일 받아 PC에 복사 | 핸드폰에서 바로 (Vibe coding) |
| 순이익 갱신 | PC 앞에 앉아야 | 핸드폰에서 숫자 입력 |

---

## 준비물

이 `cloud` 폴더 안의 모든 것 — 스크립트 11개, parquet/csv 시드 데이터, `.github` 폴더,
`requirements.txt`, `.gitignore` — 가 그대로 저장소에 올라갑니다.
**시드 데이터가 들어 있으므로, 클라우드 첫 실행이 실패해도 대시보드는 바로 뜹니다.**

---

## 1단계 — GitHub 저장소 (10분, PC에서 한 번만)

1. `github.com` 가입 (무료)
2. 우측 상단 **+** → **New repository**
   - 이름: `kospi-dashboard` (아무거나)
   - **Private** 선택 (공개 안 됨)
   - **Create repository**
3. PC에서 이 `cloud` 폴더를 통째로 올립니다:

```powershell
cd <이 cloud 폴더 경로>
git init
git add .
git commit -m "최초 등록"
git branch -M main
git remote add origin https://github.com/<내아이디>/kospi-dashboard.git
git push -u origin main
```

> `git`이 없다고 나오면 `git-scm.com`에서 설치 후 다시.

---

## 2단계 — API 키 등록 (5분)

`.env`는 절대 올리지 마세요(.gitignore가 막아줍니다). 대신 **Secrets**에 넣습니다.

저장소 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| 이름 | 값 |
|---|---|
| `KRX_ID` | KRX 아이디 |
| `KRX_PW` | KRX 비밀번호 |
| `ECOS_KEY` | 한국은행 API 키 |
| `FRED_KEY` | FRED API 키 |

---

## 3단계 — 자동 실행 켜기 (2분)

1. 저장소 → **Actions** 탭 → 워크플로 활성화 승인
2. 왼쪽 **대시보드 자동 갱신** 선택 → **Run workflow** 로 첫 실행

초록 체크면 성공. 빨간 X면 눌러서 로그를 보면 원인이 나옵니다.

---

## 4단계 — 대시보드 웹주소 (3분)

저장소 → **Settings** → **Pages**
- **Source**: `Deploy from a branch`
- **Branch**: `main` / 폴더 `/docs` → **Save**

1~2분 뒤 접속됩니다:
```
https://<내아이디>.github.io/kospi-dashboard/
```
**이 주소를 핸드폰 홈화면에 추가**하세요. 앱처럼 열립니다.

---

## 이제 핸드폰에서

### 대시보드 보기
홈화면 아이콘 탭. 끝. (매일 18:30 자동 갱신된 최신 화면)

### 지금 바로 갱신 + 순이익 입력
1. 저장소 → **Actions** → **대시보드 자동 갱신** → **Run workflow**
2. 칸이 뜹니다:
   - **올해 예상순이익(조원)**: 예 `606`
   - **내년 예상순이익(조원)**: 예 `946`
   - (선택) 예상PER 직접 입력
   - 다 비워도 됨 → 데이터만 갱신
3. 초록 버튼 → 2~3분 뒤 대시보드 반영

> 순이익은 FnGuide·증권사 리포트에서 분기에 한 번만 확인하면 됩니다.
> 지수 변동은 시가총액으로 자동 반영되므로 매일 넣을 필요 없습니다.

### 코드 고치기 (Vibe coding)
- **간단한 수정**: 깃허브 웹에서 파일 → 연필 아이콘 → 수정 → Commit
  (커밋하면 다음 실행부터 반영)
- **본격 작업**: **Claude Code**를 저장소에 연결하면, 저에게 말로 시키고
  제가 직접 파일을 고쳐 커밋합니다. Claude 모바일 앱에서도 됩니다. (Pro/Max 등 유료)

---

## KRX 수집이 클라우드에서 막히면

GitHub 서버는 해외(미국)에 있어 **KRX가 접속을 막을 수 있습니다.**
ECOS·FRED는 대개 문제없습니다. 막히면 절충안:

**집 PC가 데이터만 올리고, 나머지는 클라우드가**

집 PC의 `daily_update.bat` 끝에 세 줄 추가:
```bat
git add *.parquet *.csv
git commit -m "data %date%"
git push
```
집 PC를 켠 날에만 데이터가 갱신되지만, **핸드폰에서 보고 고치는 건 그대로** 됩니다.

---

## 파일 설명 (참고)

| 파일 | 역할 |
|---|---|
| `build_dashboard.py` | 데이터 → dashboard.html 생성 (본체) |
| `collect_krx/ecos/fred/flow.py` | 각 소스 수집기 |
| `update_all.py` | 수집기 4개 일괄 실행 |
| `update_fwd_per.py` | 예상순이익 → 선행PER 계산 (`--ni FY1 FY2`) |
| `serve_dashboard.py` | 로컬 서버 (PC에서 버튼 쓸 때만) |
| `.github/workflows/update.yml` | 클라우드 자동 실행 정의 |
| `*.parquet`, `*.csv` | 시드 데이터 (첫 실행 전에도 대시보드가 뜨게) |
