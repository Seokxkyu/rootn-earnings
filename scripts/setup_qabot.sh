#!/usr/bin/env bash
# Q&A 봇(@RootN_QA_bot) launchd 상시 데몬 등록.
#
# 수집 파이프라인(com.rootn.capiq-pipeline)과 별개인 KeepAlive 데몬으로,
# 죽으면 자동 재기동된다. long-polling이라 인바운드 포트가 필요 없다.
#
# 전제: .env에 QA_BOT_TOKEN, XAI_API_KEY 존재. venv 구성 완료(setup_mac.sh).
#
# Usage: bash scripts/setup_qabot.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LABEL="com.rootn.earnings-qabot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON_BIN="$ROOT/.venv/bin/python"

[ -f ".env" ] || { echo "❌ .env 없음"; exit 1; }
grep -q "^QA_BOT_TOKEN=" .env || { echo "❌ .env에 QA_BOT_TOKEN 없음"; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" logs
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${ROOT}/scripts/qa_bot.py</string>
    </array>
    <key>WorkingDirectory</key><string>${ROOT}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>${ROOT}/logs/launchd_qabot.out.log</string>
    <key>StandardErrorPath</key><string>${ROOT}/logs/launchd_qabot.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>LANG</key><string>en_US.UTF-8</string>
        <key>PYTHONIOENCODING</key><string>utf-8</string>
    </dict>
    <key>LimitLoadToSessionType</key><string>Aqua</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "등록됨: $PLIST"
launchctl list | grep "$LABEL" || true
echo "완료. 텔레그램 방에서 '/ask <질문>'으로 테스트하세요."
