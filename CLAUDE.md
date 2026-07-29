# CapIQ Earnings Tracker

CapIQ earnings transcript 수집 → Grok 요약 → Telegram 전송 파이프라인.
스케줄러(Windows 작업 스케줄러 / Mac launchd)가 매일 08:30·15:00에 `run_daily_pipeline.py --heartbeat` 실행.

## 구조 (정본 = scripts/, notebook은 실험용)

- `scripts/collect_capiq_transcripts.py` — Playwright(+설치된 Chrome, `.browser_profile` 세션 재사용)로
  CapIQ에 저장된 기본 transcript 페이지의 **현재 보이는 row만** 수집. 별도 universe/티커 리스트 없음.
  WORD 우선, PDF fallback. 중복 기준 = 정규화된 기업명+발표일 (`transcripts/manifest.csv`).
  신규분은 `output/collection_runs/latest.json`에 기록.
- `scripts/run_summary_pipeline.py` + `scripts/summary_lib/` — **종목별 스트리밍**:
  [요약 → 즉시 전송 → `.sent` 마커] 순차 처리. 재실행 시 마커 있음=스킵, md만 있음=전송만 재시도,
  없음=요약+전송. 한 종목 실패는 건너뛰고 계속(있으면 exit 1). 프롬프트 수정은 `summary_lib/prompts.py`만.
- `scripts/run_daily_pipeline.py` — 오케스트레이터. 수집 exit 코드: 0=정상(신규 0 포함),
  2=세션 만료(사람이 `--setup`으로 MFA 재로그인 필요), 3=그리드 0행(로드 실패 의심), 그 외=일반 실패.

## Telegram 라우팅 (2026-07 확정)

| 스트림 | 대상 |
|---|---|
| 종목 요약 | **채널 "RootN Earnings"** (`TELEGRAM_CHAT_ID`) |
| 운영 알림 (완료·heartbeat) | 개인 채팅 (`ops_from_env()`: OPS_CHAT_ID→ALERT_CHAT_ID 폴백) |
| 장애 알림 | 개인 채팅 (`ALERT_BOT_TOKEN`/`ALERT_CHAT_ID`) |
| 일본 기업 추가 전송 | `JP_BOT_TOKEN`/`JP_TELEGRAM_CHAT_ID` (숫자 티커일 때) |

## ⚠️ 절대 규칙

1. **개발/테스트 중 채널 전송 금지.** 테스트 전송은 반드시 개인 채팅으로 우회:
   `TELEGRAM_CHAT_ID=<개인chat_id> python scripts/...` (`load_env_file`은 기존 환경변수를 안 덮어씀,
   개인 chat_id는 .env의 ALERT_CHAT_ID와 동일). 채널 전송은 사용자가 "실전 적용"을 명시할 때만.
   채널은 팀원이 구독하며 과거 메시지가 신규 구독자에게 전부 보인다.
2. 시크릿은 전부 `.env` (git 제외). 파일·코드에 저장 금지.
3. 장애 시 복구는 `run_summary_pipeline.py --send` 재실행 (멱등, 미전송분만 재처리).
   `run_daily_pipeline.py` 재실행은 latest.json을 덮어쓰므로 복구 용도로 쓰지 말 것.
4. **한 머신에서만 스케줄 실행** — 두 머신이 같이 돌면 채널 이중 전송 (docs/mac_migration.md 참고).

## 운영 이력 요약

- 2026-07-22: 콜드스타트 페이지 로드 실패 → goto 3회 재시도 + traceback 로깅 보강
- 2026-07-28: 요약 전송을 개인 채팅 → 채널로 전환, 운영 알림은 개인으로 분리
- 2026-07-29: 콘솔 창 닫힘(0xC000013A)으로 배치 전멸 → 스트리밍(종목별 요약→전송→마커) 전환
- Mac 이식: `docs/mac_migration.md` + `scripts/setup_mac.sh`
