# 다시, 일하다 — 중장년 채용정보

전국 공공기관 채용공고를 검색하는 정적 웹사이트입니다. 공무직·무기계약직을 우선 표시하고 지역, 고용형태, 경력, 학력을 필터링합니다. 기관 원문과 지원 자격·전형 절차를 확인할 수 있습니다. 모바일 320px부터 지원하며 광고 배치 공간을 마련했습니다. 실제 광고·추적 스크립트는 포함하지 않습니다.

## 로컬 실행

Python 3.12 표준 라이브러리만으로 수집과 빌드가 가능합니다.

```sh
python -m unittest discover -v
python build.py
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

기존 체크아웃에서 작업하세요. 별도 Git worktree는 필요하지 않습니다. `dist`는 웹페이지, 스타일, JavaScript, 공개 피드, `.nojekyll`만 포함합니다. 서버 코드, 환경 설정, 테스트는 배포하지 않습니다.

## ALIO 데이터 수집

서버 환경에 `ALIO_API_KEY`를 안전하게 주입하고 실행합니다. 기본 주소는 `https://opendata.alio.go.kr`이며 `ALIO_BASE_URL`로 지정할 경우에도 이 주소만 허용합니다. 키를 명령행 인수, 브라우저, 파일이나 로그에 기록하지 마세요.

```sh
python collect.py
```

공식 Swagger 명세: <https://opendata.alio.go.kr/new/v2/api-docs?group=recruit>

- `POST /new/v1/recruit/list.do`: `serviceKey`, `pageNo`, `numOfRows`, `ongoingYn=Y`
- `POST /new/v1/recruit/detail.do`: `serviceKey`, `sn`
- 목록의 모든 페이지를 수집하고 게시 대상 공고마다 상세 API의 일련번호를 대조합니다.
- 실패하거나 응답 구조가 변경되면 기존 `jobs.json`과 수집 시각을 보존하고 실패 종료합니다. 리디렉션을 통한 키 전달을 거부합니다.
- API 원본 응답 전체를 게시하지 않고 공개 필드만 내보냅니다. 키가 응답에 반사되면 게시를 중단합니다.

### 현재 실제 검증 상태 (2026-11-01)

인증 API는 공식 명세대로 호출했으나 목록과 상세가 `SERVICETIMEOUT_ERROR`(코드 5)를 반환했고 일부 목록 요청은 연결이 끊겼습니다. 인증 API 성공 또는 인증키 유효성을 확인했다고 주장하지 않습니다.

미리보기에는 **ALIO 공식 공개 조회 화면의 실제 목록·상세 데이터**를 사용했습니다. 아래는 인증 API와 구분되는 명시적인 대체 모드이며, 인증 API 호출 성공으로 간주하지 않습니다.

```sh
python collect.py --public-preview
```

공개 조회 `/new/odaApiMng/recrutInquiryAjaxList.do`에서 진행 중 482건을 조회하고, 필터링한 모든 게시 대상의 `/new/odaApiMng/recrutInquiryAjaxDetail.do` 상세를 확인하여 421건을 게시했습니다. 날짜·원문 URL·필수 필드 검증을 통과한 공고만 포함됩니다. HTTP 원문, 누락되거나 유효하지 않은 원문, 종료·미시작 공고는 게시하지 않습니다. 원문 URL은 임의의 기관 홈페이지나 포털 링크로 바꾸지 않습니다.

이 모드의 피드는 `source: alio-public-preview`, `authenticated_api_verified: false`로 표시하며 웹페이지에서도 인증 API 연결 대기 상태를 알립니다. 원본 데이터가 없을 때 가상 공고를 만들지 않습니다.

## 분류와 마감 정책

- 공무직: 원본 공고 제목 또는 고용형태에 `공무직`이 명시된 경우입니다. 공고 내 모든 직종이 공무직이라는 뜻은 아닙니다.
- 무기계약직: 원본 고용형태에 명시된 경우만 태그를 부여합니다.
- 학력무관: 원본 학력 목록에 `학력무관`이 명시된 경우만 포함합니다.
- 경력무관: 원본 경력 구분이 정확히 `경력무관`인 경우만 포함합니다. `신입+경력`은 별도 조건이며 무관으로 추정하지 않습니다.
- 알 수 없는 조건은 `미확인`으로 남깁니다. 연령·정년·직종별 요건에 따라 지원이 제한될 수 있습니다. 중장년 전용 공고 또는 지원 가능 여부를 보장하지 않습니다.
- ALIO의 광주·전남 통합 지역을 유지합니다. 전국 지역을 조회할 수 있지만 ALIO에 없는 기관의 공고까지 포괄한다고 보장하지 않습니다.
- 수집 시와 브라우저에서 한국 날짜 기준으로 종료일이 지난 공고, 시작일 전 공고를 제외합니다. 브라우저는 1분마다 재검사합니다. 당일 마감 시각과 조기 종료는 기관 원문 확인이 필요합니다.
- 수집 후 48시간이 지나면 오래된 데이터임을 알립니다.

## 브라우저 검증

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install --with-deps chromium
python smoke_ui.py
```

시스템 `chromium` 또는 Playwright Chromium을 사용합니다. `CHROMIUM_EXECUTABLE`로 경로를 지정할 수 있습니다. 실제 피드와 고정된 테스트 데이터를 사용해 검색·필터·상세 모달·원문 링크·초기화·더 보기·정렬, 320/390/768/1440px 화면, XSS, 불명확한 조건, 한국 자정의 마감 전환, 피드 장애 처리를 검사합니다. 고정 시각으로 기존 피드를 검증하므로 과거 공고가 실제 사용자 화면에서 다시 노출되지는 않습니다.

## GitHub Pages 배포

1. 저장소 **Settings → Pages → Build and deployment → Source → GitHub Actions**를 선택합니다.
2. **Settings → Secrets and variables → Actions → New repository secret**에서 `ALIO_API_KEY`를 등록합니다. 클라우드 환경의 키는 GitHub Actions로 자동 복사되지 않습니다. 공개 조회 미리보기는 키가 없어도 동작합니다.
3. **Actions → Collect, test and deploy job listings → Run workflow → main → Run workflow**를 실행합니다.
4. 성공한 실행의 `deploy` 작업과 `github-pages` 환경에 실제 접속 주소가 표시됩니다. 예상 주소는 `https://ytbhana01-tech.github.io/midcareer-jobs/`이지만 배포 성공 전에는 활성 주소로 간주하지 마세요. 비공개 저장소는 계정 플랜의 Pages 지원 여부도 확인해야 합니다.

`main` 변경 및 매일 10:17·16:17 KST에 갱신·검증·배포합니다. 인증 API가 실패하면 명시적인 공개 조회 미리보기로 시도하고, 두 경로 모두 실패하면 기존 피드와 원래 시각을 유지합니다. 공개 웹 산출물만 Pages로 업로드합니다. 실행 토큰은 `contents: read` 및 배포 작업의 `pages: write`, `id-token: write`로 제한합니다. 수집기는 읽기 전용이며 Git 푸시를 수행하지 않습니다.
