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
scripts/run_daily_pipeline.py         통합 진입점: 수집 → 요약 → 전송 + 운영 알림
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

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `XAI_API_KEY` | O | Grok 요약 API 키 |
| `XAI_MODEL` | - | Grok 모델 (기본 `grok-4.5`) |
| `TELEGRAM_BOT_TOKEN` | O | 종목 요약 전송 봇 토큰 |
| `TELEGRAM_CHAT_ID` | O | 전송 대상 chat ID |
| `ALERT_BOT_TOKEN` | - | 장애 알림 전용 봇 토큰 (없으면 요약 봇으로 폴백) |
| `ALERT_CHAT_ID` | - | 장애 알림 대상 chat ID (없으면 `TELEGRAM_CHAT_ID` 재사용) |
| `CAPIQ_EMAIL` | - | 세션 만료 재로그인 시 이메일 자동 입력용 (없으면 수동 입력) |
| `CAPIQ_PASSWORD` | - | 세션 만료 재로그인 시 비밀번호 자동 입력용 (없으면 수동 입력) |

### 알림 채널 분리

- **종목 요약 + "✅ 완료" 알림** → `TELEGRAM_BOT_TOKEN` 봇
- **장애 알림**(세션 만료, 수집 실패, 요약/전송 실패) → `ALERT_BOT_TOKEN` 봇
- `ALERT_BOT_TOKEN`이 없으면 장애 알림도 요약 봇으로 간다(단일 봇 운영).

## 세션 만료 처리

로그인 세션은 `.browser_profile`에 저장되어 "Keep Me Signed In"으로 오래 유지된다.
세션이 만료되면:

- `CAPIQ_EMAIL` / `CAPIQ_PASSWORD`가 있으면 이메일·비밀번호는 자동 입력된다.
- **MFA 4자리 코드는 자동 조회하지 않는다.** 인증 메일이 Gmail이 아니므로 IMAP
  자동조회 로직은 제거했다. 세션 만료 시 열린 브라우저 창에서 사용자가 직접 MFA 코드를
  입력해 로그인을 완료한다 (`--setup` 실행 시 최대 5분 대기).
- 무인 실행 중 만료되면 collect가 exit 2로 끝나고, 통합 파이프라인이
  "⚠️ 세션 만료" Telegram 알림을 보낸다. 이후 사람이 한 번 `--setup`으로 로그인하면 된다.

## 자동화 (Windows 예약 작업)

`run_daily_pipeline.py`가 수집 → 요약 → 전송을 한 번에 실행하는 통합 진입점이다.
운영 알림도 여기서 보낸다.

- **완료·heartbeat** → 요약 봇(`TELEGRAM_BOT_TOKEN`)
- **세션 만료·수집 실패·요약/전송 실패** → 장애 봇(`ALERT_BOT_TOKEN`)
- 신규 transcript가 없으면 요약·전송을 건너뛰고 조용히 종료한다.

수동 실행:

```powershell
python scripts\run_daily_pipeline.py              # 수집 → 요약 → 전송
python scripts\run_daily_pipeline.py --heartbeat  # 신규 0건이어도 완료 알림
python scripts\run_daily_pipeline.py --notify-test # 두 봇 알림 경로만 점검
```

예약 작업 등록(기본 매일 08:30 KST, 실행 한도 60분):

```powershell
python scripts\collect_capiq_transcripts.py --setup    # 최초 1회 로그인 세션 저장
powershell scripts\register_collection_task.ps1 -Times "08:30" -ExecutionMinutes 60
```

- 태스크 이름: `CapIQ Daily Pipeline`
- 실행 Python은 시스템 python(Playwright 설치 필요)을 자동 선택하며, `-PythonPath`로 지정할 수도 있다.
- 시각은 시스템 시간대(KST) 기준. 복수 실행은 `-Times "08:30","13:00"`.
- **headful 브라우저 + interactive 로그온**이라, 예약 시각에 PC가 켜져 있고 로그인돼 있어야 한다(`-StartWhenAvailable`이라 잠자기 후 깨어나면 실행). 동시 실행은 `IgnoreNew`로 막는다.

관리 명령:

```powershell
Get-ScheduledTask -TaskName 'CapIQ Daily Pipeline'          # 상태 확인
Start-ScheduledTask -TaskName 'CapIQ Daily Pipeline'        # 즉시 1회 실행
powershell scripts\register_collection_task.ps1 -Unregister # 등록 해제
```

세션이 만료되면 장애 봇으로 "⚠️ 세션 만료" 알림이 온다. 그때 한 번
`python scripts\collect_capiq_transcripts.py --setup`을 실행하고 브라우저에서
MFA 4자리만 입력하면 세션이 다시 유지된다.
