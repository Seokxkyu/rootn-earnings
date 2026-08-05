#!/usr/bin/env bash
# CapIQ 파이프라인 Mac(mini) 설치 스크립트.
#
# Windows의 register_collection_task.ps1 대응물. 저장소를 clone한 뒤 이 스크립트를
# 실행하면 venv·의존성 설치와 launchd 스케줄(매일 07:30/09:30/13:30/16:30) 등록까지 끝난다.
#
# 실행 전 Windows에서 복사해 와야 하는 것:
#   1. .env                      (CAPIQ/XAI/TELEGRAM 키 — git에 없음)
#   2. transcripts/manifest.csv  (중복 방지 원장 — 없으면 기존 수집분을 전부 재전송한다!)
#
# 실행 후 해야 하는 것:
#   1. .venv/bin/python scripts/collect_capiq_transcripts.py --setup
#      → 열리는 브라우저에서 CapIQ 로그인 + MFA 1회 (Windows 프로필 복사는 불가:
#        Chrome 쿠키가 OS 키체인에 묶여 있어 다른 OS에서 복호화되지 않는다)
#   2. .venv/bin/python scripts/run_daily_pipeline.py --notify-test   (알림 경로 확인)
#   3. 검증 완료 후 Windows 작업 스케줄러의 "CapIQ Daily Pipeline" 비활성화
#      (두 머신이 같이 돌면 채널에 요약이 이중 전송된다)
#
# Usage: bash scripts/setup_mac.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PLIST_LABEL="com.rootn.capiq-pipeline"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
PYTHON_BIN="$ROOT/.venv/bin/python"

echo "== 1/4 사전 점검 =="
command -v python3 >/dev/null 2>&1 || { echo "❌ python3 없음. 'brew install python' 후 재실행하세요."; exit 1; }
if [ ! -d "/Applications/Google Chrome.app" ]; then
    echo "⚠ Google Chrome이 설치돼 있지 않습니다. 수집기가 channel=chrome을 쓰므로 설치가 필요합니다."
fi
[ -f ".env" ] || echo "⚠ .env 없음 — Windows에서 복사해 오세요."
if [ ! -f "transcripts/manifest.csv" ]; then
    echo "⚠ transcripts/manifest.csv 없음 — 복사하지 않으면 CapIQ에 보이는 row 전부를 '신규'로 재수집·재전송합니다!"
else
    # Windows에서 복사해 온 manifest의 경로 구분자(\)를 POSIX(/)로 정규화.
    # 중복 키는 기업명+발표일이라 dedupe에는 영향 없지만, 파일 참조가 깨지는 걸 막는다.
    sed -i '' 's|\\|/|g' transcripts/manifest.csv
    echo "   manifest.csv 경로 구분자 정규화 완료"
fi

echo "== 2/4 venv + 의존성 =="
[ -d .venv ] || python3 -m venv .venv
"$PYTHON_BIN" -m pip install --upgrade pip --quiet
"$PYTHON_BIN" -m pip install -r requirements.txt --quiet
# 브랜디드 Chrome이 이미 있으면 실패해도 무방 (수집기는 설치된 Chrome을 그대로 쓴다)
"$PYTHON_BIN" -m playwright install chrome >/dev/null 2>&1 || true
echo "   완료: $PYTHON_BIN"

echo "== 3/4 launchd LaunchAgent 등록 (매일 07:30 / 09:30 / 13:30 / 16:30) =="
mkdir -p "$HOME/Library/LaunchAgents" logs
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${ROOT}/scripts/run_daily_pipeline.py</string>
        <string>--heartbeat</string>
    </array>
    <key>WorkingDirectory</key><string>${ROOT}</string>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
    </array>
    <key>StandardOutPath</key><string>${ROOT}/logs/launchd_pipeline.out.log</string>
    <key>StandardErrorPath</key><string>${ROOT}/logs/launchd_pipeline.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>LANG</key><string>en_US.UTF-8</string>
        <key>PYTHONIOENCODING</key><string>utf-8</string>
    </dict>
    <key>LimitLoadToSessionType</key><string>Aqua</string>
</dict>
</plist>
PLIST

# 기존 등록이 있으면 내리고 다시 올린다.
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
echo "   등록됨: $PLIST_PATH"
launchctl list | grep "$PLIST_LABEL" || true

echo "== 4/4 절전/세션 설정 (수동 확인 필요) =="
cat <<'GUIDE'
  Mac mini 권장 설정:
  - 절전 금지:      sudo pmset -a sleep 0 displaysleep 10
    (launchd는 잠들며 놓친 스케줄을 깨어날 때 실행해 주지만, 정시성을 위해 상시 깨움 권장)
  - 자동 로그인 ON: 시스템 설정 > 사용자 및 그룹 (수집기 브라우저가 GUI 세션 필요)
  - FileVault 사용 시 재부팅 후 반드시 1회 수동 로그인해야 스케줄이 살아난다.

  다음 단계:
  1) .venv/bin/python scripts/collect_capiq_transcripts.py --setup   ← CapIQ 로그인+MFA 1회
  2) .venv/bin/python scripts/run_daily_pipeline.py --notify-test    ← 알림 경로 확인
  3) 검증 후 Windows의 "CapIQ Daily Pipeline" 태스크 비활성화 (이중 전송 방지)
GUIDE
echo "설치 완료."
