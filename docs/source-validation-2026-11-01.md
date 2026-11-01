# 실제 수집처 검증 — 2026-11-01 KST

대상: PR #2, `feat/issue-1-multi-source`. 검증은 적용된 새 네트워크 설정으로 수행했다. 운영 배포·병합·기존 피드 교체는 하지 않았다.

## 환경

Cloud Environment 상태에서 `observations_current: true`, 네트워크 `state: enforced`를 확인했다. data.go.kr, apis.data.go.kr, www.busan.go.kr, opendata.alio.go.kr이 허용되어 있었다. ALIO 키/기본 주소는 ready, NARA_API_KEY는 미설정이다. 프록시·CA·TLS 검증을 유지했으며 ALIO 키를 다른 기관에 전송하지 않았다.

## 나라일터

- [데이터셋 15156780](https://www.data.go.kr/data/15156780/openapi.do): HTTP 200. 페이지에 포함된 공식 Swagger 2.0을 `nara-api-reference.json`으로 보관했다. 이는 명세이며 실제 성공 응답 fixture가 아니다.
- 페이지의 이용허락범위는 **이용허락범위 제한 없음**, 무료, 개발/운영 자동승인으로 표시된다. 활용신청 승인이나 현재 키의 권한을 확인했다는 의미는 아니다.
- 공식 기본 주소: `https://apis.data.go.kr/1760000/PblJobService`. GET `/getList`, `/getItem` 등. 응답 XML의 루트는 `response`이며 목록 경로는 `body.items.item`, 전체 건수는 `body.totalCount`이다.
- 목록 요청의 필수 인수: `serviceKey`, `Pblanc_ty`, `Instt_se`, `Sort_order`. 선택 페이지 인수는 `pageNo`, `numOfRows`. 필수 검색 인수의 실제 허용값과 성공 코드 값은 인증 성공 응답으로 재확인해야 한다.
- 목록의 `idx`/`title`/`insttname`/`enddate`는 ID/제목/기관/마감일 후보다. `enddate`는 yyyymmdd. 원문 URL은 목록에 없고 `/getItem?idx=...`의 `link01`~`link03`에 있다. 상세 연계 없는 기존 범용 매핑을 실제 계약에 맞는 구현이라고 주장할 수 없다.
- 키를 보내지 않은 `/getList` 탐색 요청은 HTTP 400, XML `INVALID_REQUEST_PARAMETER_ERROR`, 코드 10을 반환했다. 필수 인수가 없는 요청과 키가 없는 검색 인수 포함 요청 모두 같은 결과였다. 이것은 호스트 접근 확인일 뿐 실제 목록 수집 성공 또는 인증키만 추가하면 성공한다는 증거가 아니다.
- **결과: 비활성 유지.** 전용 승인 키, 실제 목록/상세 응답, 원문 호스트·robots·접수기간 검증이 남아 있다. 응답 필드나 URL을 추측하여 `sources.json`을 활성화하지 않았다.

## 부산광역시

- [공식 채용정보 게시판](https://www.busan.go.kr/depart/jobgonji01): 처음 503, 재시도 200. HTML은 공식 피드 링크와 정책을 찾기 위한 검토에만 사용했으며 공고 수집기로 추가하지 않았다.
- 게시판의 RSS 버튼이 직접 가리킨 [공식 RSS](https://www.busan.go.kr/depart/jobgonji01.rss): HTTP 200, RSS 2.0 항목 10건.
- 실제 item 필드: `title`, `link`, `content:encoded` (`http://purl.org/rss/1.0/modules/content/`), `pubDate`, `author`. 기관·접수 마감일·접수 시작일·고유 guid는 별도 필드로 제공되지 않는다. `author`는 개인 작성자이므로 기관명으로 매핑하지 않았다.
- 링크 10건 전부 HTTP다. 현재 HTTPS 원문 기준에 맞지 않는다. HTTPS로 자동 변환하거나 게시일을 마감일로 대신하지 않았다.
- 본문에 공고기간과 접수기간이 함께 있는 사례가 있었다. 정규식으로 첫 날짜를 가져오는 방식은 실제 접수기간을 잘못 표시할 수 있어 추가하지 않았다.
- [robots.txt](https://www.busan.go.kr/robots.txt): 처음 503, 이후 두 번 401 및 기관 보안 차단 안내. 수집 허용 여부를 확인하지 못했으므로 기존 fail-closed 정책을 유지했다.
- [저작권 보호정책](https://www.busan.go.kr/cright): HTTP 200. 공공누리 표시·유형별 조건을 확인하고, 표시 없는 자료는 담당부서와 사전 협의하도록 규정한다. RSS 제공만으로 개별 공고의 상업적 재이용·변경 허용을 확인할 수 없다.
- **결과: RSS 다운로드는 성공, 게시 가능한 채용 데이터 수집은 미완료.** 마감일/기관/HTTPS 원문 계약, robots 접근, 항목별 재이용 조건 확인이 필요하므로 비활성 유지.

## ALIO 및 회귀 검증

- 기존 `collect.collect(False)` 실제 호출: `ALIO transport/JSON error; credentials withheld`로 실패. 인증 성공이나 인증키 유효성을 주장하지 않는다.
- 기존 `collect.collect(True)` 실제 호출: 목록과 필터링된 상세 수집 성공, **421건**, `updated_at: 2026-11-01T19:04:09+09:00`. 결과는 임시 파일에만 저장했다. 인증 API 성공과 구분되는 기존 공개 조회 대체 경로다.
- 독립 `collect.py`, ALIO fallback, 운영 `jobs.json`, 기존 수집 시각, 활성화 설정은 변경하지 않았다. 새 출처가 연결되었다고 표시하지 않는다.
- 단위 테스트 44개 통과. 출처 실패 시 이전 데이터/시각 보존, 미확인 원문 전송 실패, 비밀정보 반사 방지, 계약·키 게이트 포함.

- `python smoke_ui.py` 통과: 실제 기존 피드, 검색·필터·상세·더 보기·정렬, 320/390/768/1440px, 다중 출처 표시, XSS, KST 마감과 장애 상태. 페이지 오류 0건.
- `git diff --check` 통과. 빌드는 허용된 공개 자산만 포함한다.

## 후속 조건

나라일터는 환경 및 Actions에 승인된 전용 키를 안전하게 설정한 후 실제 응답으로 상세 연계를 구현해야 한다. 부산시는 구조화된 접수기간과 이용조건을 제공하는 공식 계약이 필요하다. 현재는 외부 접근/자료·자격 요건이 남아 있으므로 PR을 draft로 유지하며 배포하지 않는다. 사용자에게 키 값을 채팅으로 요청하거나 기관에 연락하지 않았다.
