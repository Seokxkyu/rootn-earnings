# Capital IQ Transcript Collector

S&P Capital IQ Pro의 transcript 기본 페이지에 현재 표시되는 `Earnings Call`
row만 수집하는 자동화 스크립트다. 별도 Universe 파일이나 기업 검색 로직은
사용하지 않는다. 수집 대상은 사용자가 Capital IQ 안에서 저장해둔 기본 페이지
상태가 그대로 결정한다.

## 현재 동작

1. `.browser_profile/`의 로그인 세션을 재사용한다.
2. 세션이 만료되면 환경변수 계정으로 자동 재로그인을 시도한다.
3. 기본 transcript 페이지에 현재 보이는 `Earnings Call` row만 읽는다.
4. WORD를 우선 다운로드하고, WORD가 없으면 PDF로 대체한다.
5. `기업명 + 발표일`이 `transcripts/manifest.csv`에 있으면 건너뛴다.
6. 새 transcript는 수집일 기준 `transcripts/YYYY-MM-DD/` 폴더에 저장한다.
7. 한 번에 최대 `max_per_run`개의 새 transcript를 저장한다.
8. 같은 실행에서 받은 파일 목록을 `output/collection_runs/`에 JSON, CSV로 남긴다.

`Company List.xlsx`는 현재 수집기에 사용되지 않는다.

## 구조

```text
config/collector_config.json          실행 설정
scripts/collect_capiq_transcripts.py  수집 본체
scripts/register_collection_task.ps1  Windows 예약 작업 등록
scripts/run_summary_pipeline.py       요약 -> Telegram 전송 CLI
scripts/summary_lib/                  요약 파이프라인 모듈 (notebook 모듈화 버전)
scripts/send_latest_telegram_summary.py  최신 요약 md 1개 수동 전송 도구
notebooks/                            대화형 실험용 notebook (정본 로직은 summary_lib)
legacy/                               사용하지 않는 과거 수동 수집 도구
docs/                                 설계 문서와 과거 테스트 기록
transcripts/                          날짜별 다운로드 파일과 manifest.csv
output/collection_runs/               실행별 신규 다운로드 목록(JSON, CSV)
output/summaries/grok/                요약 md와 배치 JSON/CSV, latest_batch.json
logs/                                 실행 로그와 선택적 HTML dump
.browser_profile/                     Capital IQ 로그인 세션
```

## 요약 및 Telegram 전송

`telegram_summary.ipynb`의 로직을 `scripts/summary_lib/` 모듈로 분리했다.

```text
summary_lib/config.py           .env 로딩, 경로, Grok/Telegram 설정
summary_lib/transcript_io.py    입력 선택(latest.json 또는 폴더), docx/pdf 텍스트 추출
summary_lib/metadata.py         티커(거래소 표기 우선)/분기/세션/컨센서스 블록 추출
summary_lib/prompts.py          요약 프롬프트와 파라미터 (스타일 수정은 이 파일만)
summary_lib/grok_client.py      Grok API 호출, 429/5xx 백오프 재시도
summary_lib/summarizer.py       청크 분할 -> 청크 요약 -> 최종 요약, 멱등성 스킵
summary_lib/outputs.py          배치 JSON/CSV 저장, latest_batch.json 갱신
summary_lib/telegram_client.py  메시지 빌드/분할/전송(재시도 포함)
```

실행:

```powershell
python scripts\run_summary_pipeline.py                # 최근 수집분 요약 (전송 안 함)
python scripts\run_summary_pipeline.py --send         # 요약 + Telegram 전송
python scripts\run_summary_pipeline.py --input transcripts\2026-07-10
python scripts\run_summary_pipeline.py --list-only    # 대상 파일 확인만
python scripts\run_summary_pipeline.py --force        # 기존 요약 무시하고 재요약
```

동작 원칙:

- 기본 입력은 `output/collection_runs/latest.json` (방금 수집분만 처리)
- 요약 md가 이미 있으면 건너뛴다 -> 여러 번 실행해도 중복 요약·중복 전송 없음
- 배치의 모든 신규 요약을 전송한다 (최신 1개만 보내는 방식 아님)
- 요약 md는 transcript와 같은 날짜 폴더명으로 `output/summaries/grok/YYYY-MM-DD/`에 저장

## 설정

`config/collector_config.json`:

```json
{
  "download_format": "word",
  "max_per_run": 12
}
```

- `download_format`: `word` 또는 `pdf`
- `max_per_run`: 한 번 실행할 때 새로 받을 최대 transcript 수

## 실행

초기 로그인 세션 저장:

```powershell
python scripts\collect_capiq_transcripts.py --setup
```

일반 수집 실행:

```powershell
python scripts\collect_capiq_transcripts.py
```

현재 페이지 HTML 덤프 저장:

```powershell
python scripts\collect_capiq_transcripts.py --dump
```

## 출력

- 다운로드 파일: `transcripts/YYYY-MM-DD/*.docx` 또는 `*.pdf`
- 수집 이력: `transcripts/manifest.csv`
- 실행 결과 JSON: `output/collection_runs/YYYY-MM-DD/collection_run_*.json`
- 실행 결과 CSV: `output/collection_runs/YYYY-MM-DD/collection_run_*.csv`
- 최신 실행 결과: `output/collection_runs/latest.json`

`latest.json`은 후속 요약 또는 Telegram 전송 단계가 "방금 실행에서 새로 받은 파일만"
읽고 싶을 때 기본 입력으로 사용하면 된다.

## 환경변수

| 이름 | 설명 |
| --- | --- |
| `CAPIQ_EMAIL` | 세션 만료 시 Capital IQ 로그인 ID |
| `CAPIQ_PASSWORD` | 세션 만료 시 Capital IQ 비밀번호 |
| `GMAIL_USER` | MFA 이메일 조회용 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Gmail IMAP 앱 비밀번호 |
| `XAI_API_KEY` | Grok 요약 API 키 |
| `XAI_MODEL` | Grok 모델 (기본 `grok-4.5`) |
| `TELEGRAM_BOT_TOKEN` | Telegram 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 전송 대상 chat ID |

Gmail 환경변수는 자동 MFA 조회를 쓸 때만 필요하다.
