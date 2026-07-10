---
name: capitaliq-transcripts
description: S&P Capital IQ Pro의 저장된 기본 transcript 페이지에서 현재 표시되는 Earnings Call row를 읽어 신규 WORD transcript를 수집한다. 별도 종목 검색이나 로컬 Universe 목록은 사용하지 않으며, 기업명과 발표일로 중복을 방지한다.
---

# Capital IQ Transcript Collector

현재 수집 명세는 `README.md`와 `docs/collection_design.md`를 따른다.

## 수집 원칙

- 사용자가 Capital IQ 안에서 구성한 기본 transcript 페이지를 Universe로 사용한다.
- 화면에 현재 표시된 Earnings Call row만 처리한다.
- WORD를 우선하고, 사용할 수 없을 때 PDF로 대체한다.
- `기업명 + 발표일`이 기존 manifest에 있으면 다시 다운로드하지 않는다.
- 회사명이나 티커를 별도로 검색하지 않는다.

## 실행

일반 수집:

```powershell
& $env:CAPIQ_PYTHON E:\Earnings\scripts\collect_capiq_transcripts.py
```

`CAPIQ_PYTHON`이 없다면 Playwright가 설치된 Python의 절대경로를 사용한다.

로그인 세션을 새로 만들어야 할 때:

```powershell
& $env:CAPIQ_PYTHON E:\Earnings\scripts\collect_capiq_transcripts.py --setup
```

## 인증

- `.browser_profile`의 기존 로그인 세션을 우선 재사용한다.
- 세션 만료 시 `CAPIQ_EMAIL`, `CAPIQ_PASSWORD` 환경변수를 사용한다.
- Gmail MFA 자동 조회는 `GMAIL_USER`, `GMAIL_APP_PASSWORD`가 있을 때만 사용한다.
- 비밀번호와 MFA 코드는 코드, 문서, 로그에 기록하지 않는다.

## 결과 확인

- 다운로드: `E:\Earnings\transcripts\[회사명]\`
- 수집 이력: `E:\Earnings\transcripts\manifest.csv`
- 실행 로그: `E:\Earnings\logs\`

완료 보고에는 신규 다운로드 수, 파일명, 중복으로 건너뛴 여부, 인증 또는 파싱
실패 여부를 포함한다.
