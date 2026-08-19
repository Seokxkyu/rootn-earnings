# Mac mini 이식 체크리스트

Windows(E:\Earnings) → Mac mini로 파이프라인을 옮기는 절차. 코드 자체는 크로스플랫폼이라
옮기는 것은 **데이터 2개 + 세션 1회 + 스케줄러 교체**가 전부다.

## 1. Mac mini 준비

- [ ] Google Chrome 설치 (수집기가 `channel="chrome"` 사용)
- [ ] Python 3.12+ 설치 (`brew install python`)
- [ ] `git clone git@github.com:Seokxkyu/rootn-earnings.git ~/Earnings`

## 2. Windows에서 복사해 올 파일 (git에 없는 것)

| 파일 | 왜 필요한가 | 안 가져가면 |
|---|---|---|
| `.env` | 모든 시크릿 (CAPIQ/XAI/TELEGRAM) | 아무것도 동작 안 함 |
| `transcripts/manifest.csv` | **중복 방지 원장** (기업명+발표일) | CapIQ에 보이는 row 전부 재수집 → **채널 재전송 사고** |
| `output/summaries/grok/` (선택) | 당일 마이그레이션 시 요약 멱등성 | 같은 날 옮길 때만 의미 있음 |

`.browser_profile`은 **복사해도 소용없다** — Chrome 쿠키는 OS 키체인(DPAPI/Keychain)에
묶여 있어 다른 OS에서 복호화되지 않는다. Mac에서 로그인을 새로 한다 (아래 4단계).

## 3. 설치 스크립트 실행

```bash
cd ~/Earnings && bash scripts/setup_mac.sh
```

venv·의존성 설치, manifest 경로 정규화, launchd 등록(매일 07:30/10:30/22:30)까지 자동.

## 4. CapIQ 세션 확립 (1회)

```bash
.venv/bin/python scripts/collect_capiq_transcripts.py --setup
```

열리는 Chrome 창에서 이메일·비밀번호·MFA 4자리 입력. 이후 `.browser_profile`에 세션 유지.

## 5. 테스트 (채널 전송 금지 규칙 준수)

```bash
.venv/bin/python scripts/run_daily_pipeline.py --notify-test        # 알림 경로
TELEGRAM_CHAT_ID=<개인chat_id> .venv/bin/python scripts/run_daily_pipeline.py --heartbeat  # 풀 사이클(개인 우회)
```

## 6. 컷오버

- [ ] Windows 작업 스케줄러에서 **"CapIQ Daily Pipeline" 비활성화**
  — 두 머신이 같이 돌면 각자 manifest 기준으로 신규를 잡아 **채널 이중 전송**된다
- [ ] Mac 절전 금지: `sudo pmset -a sleep 0 displaysleep 10`
- [ ] 자동 로그인 ON (시스템 설정 > 사용자 및 그룹) — 브라우저가 GUI 세션 필요
- [ ] FileVault 사용 시: 재부팅 후 1회 수동 로그인 필요함을 기억할 것

## 운영 참고

- launchd 로그: `logs/launchd_pipeline.{out,err}.log` (+ 기존 `logs/pipeline_*.log` 그대로)
- 잠자다 놓친 스케줄은 깨어날 때 실행됨 (Task Scheduler와 달리 자동)
- 수동 실행/재등록: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.rootn.capiq-pipeline.plist`
  후 `setup_mac.sh` 재실행
- 세션 만료 시: Telegram 장애 알림 수신 → `--setup`으로 재로그인 (Windows와 동일)
