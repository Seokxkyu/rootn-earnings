# Capital IQ Transcript Collection Design

Last updated: 2026-07-09

## Scope

현재 설계는 전체 파이프라인 중 수집 단계에 집중한다.

```text
Capital IQ 기본 페이지 -> 신규 transcript 수집
-> 고정 prompt 요약 -> Telegram 전송
```

Universe는 로컬 파일로 관리하지 않는다. Capital IQ transcript 페이지에 사용자가
저장해둔 기본 필터와 정렬 결과를 그대로 사용하고, 수집기는 현재 화면에 보이는
`Earnings Call` row만 처리한다.

## Collection Rules

- 기본 형식은 WORD이며 사용할 수 없으면 PDF로 대체한다.
- 중복 기준은 정규화된 `기업명 + 발표일`이다.
- 같은 기업과 날짜가 manifest에 있으면 파일 형식과 관계없이 재수집하지 않는다.
- 발표일을 파싱하지 못한 row는 잘못된 중복 판정을 피하기 위해 건너뛴다.
- `max_per_run`은 한 실행에서 받을 수 있는 신규 파일 수를 제한한다.
- 다운로드 파일은 `transcripts/YYYY-MM-DD/` 아래에 저장한다.
- 후속 요약 파이프라인이 바로 읽을 수 있도록 실행 결과를
  `output/collection_runs/YYYY-MM-DD/`에 JSON, CSV로 남긴다.

## Authentication

- Playwright persistent Chrome profile로 기존 세션을 재사용한다.
- 세션 만료 시 `CAPIQ_EMAIL`, `CAPIQ_PASSWORD`로 재로그인한다.
- MFA 메일 자동 조회는 로그인 요청 이후 도착한 메일만 대상으로 한다.
- 인증 관련 문맥 근처의 4~8자리 숫자만 MFA 코드로 인정한다.
- 자격증명과 MFA 코드는 설정 파일에 저장하지 않는다.

## Scheduling

Windows 예약 작업은 기본적으로 매일 07:30에 실행하도록 설계되어 있다.
실제 실행 Python은 다음 우선순위로 선택한다.

1. `-PythonPath` 인자
2. `CAPIQ_PYTHON` 환경변수
3. 프로젝트 `.venv`
4. 현재 Codex 번들 Python
5. 시스템 `python`

Playwright가 headful Chrome을 사용하므로 로그인된 사용자 세션이 필요하다.
동시 실행은 `IgnoreNew`로 막는다.

## State

`transcripts/manifest.csv`는 사람이 읽을 수 있는 수집 이력이다. 별도 transcript ID나
로컬 dedupe key를 저장하지 않고, 실행 중 각 row의 기업명과 발표일로 중복 여부를
계산한다.

`output/collection_runs/latest.json`은 가장 최근 실행 결과다. 요약/전송 단계가
"이번 실행에서 새로 수집된 파일만" 읽어야 할 때 기본 입력으로 사용할 수 있다.
