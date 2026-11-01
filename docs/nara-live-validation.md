# 나라일터 공식 API 연결 검증

2026-11-01 KST, PR #2. 기존 ALIO 수집과 부산시 비활성 상태를 유지하면서 나라일터 전용 목록/상세 경로를 구현했다.

## 실제 계약 검증

- [인증 목록·상세 응답](https://github.com/ytbhana01-tech/midcareer-jobs/actions/runs/41297911356): GitHub Actions의 NARA_API_KEY로 HTTP 200 / 성공 코드 00을 받았다. 최근 30일 e04 조회는 832건이었다. 응답 샘플을 비밀정보 없이 fixture에 보관했다.
- [전체 유형 조회](https://github.com/ytbhana01-tech/midcareer-jobs/actions/runs/41298103464): Pblanc_ty/Instt_se를 빈 값으로 보내 전체 유형·기관을 조회할 수 있음을 확인했다. 같은 30일 범위의 totalCount는 2,306건이었다. 이는 마감 필터 전 목록 건수다.
- [원문 확인](https://github.com/ytbhana01-tech/midcareer-jobs/actions/runs/41298786253): 공식 페이지의 링크 처리 스크립트를 확인하고, `apmView.do?empmnsn=289736`이 HTTP 200 및 인증 API와 동일한 공고 제목을 반환하는 것을 확인했다. robots.txt도 HTTP 200이었다.
- 나라일터 실제 수집은 최근 90일 등록 공고로 제한한다. 모든 페이지를 읽고 마감·상세 대조·HTTPS 원문 제목 확인을 통과한 공고만 게시한다. 등록일은 접수 시작일로 사용하지 않는다.

## 회귀 검증

실제 XML 계약, 목록/상세 불일치, 만료일, 키 반사, 페이징 오류, 원문 실패, HTML 일반 텍스트 변환, 출처별 ID와 중복 attribution을 검사한다. UI는 나라일터 출처 필터·제목/기관/지역/본문 검색·상세 원문을 지원하며 미확인 학력/경력을 추정하지 않는다.

전체 수집 및 배포 결과는 검증 완료 후 아래에 기록한다.
