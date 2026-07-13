"""CapIQ 일일 통합 파이프라인: 수집 -> 요약 -> 전송 + 운영 알림.

Windows 예약 작업(또는 Mac launchd)에서 이 스크립트 하나만 실행하면
수집부터 Telegram 전송까지 끝난다. 각 단계의 종료 코드를 확인하고,
실패/세션 만료/완료 시 관리자에게 Telegram 운영 알림을 보낸다.

동작:
1. collect_capiq_transcripts.py 실행
   - exit 2  = 세션 만료 + 자동 재로그인 실패/불가 -> 알림 후 중단
   - exit !=0 = 기타 수집 실패 -> 알림 후 중단
   - exit 0  = 정상 (신규 0건일 수도 있음)
2. latest.json에서 신규 수집 건수 확인. 0건이면 조용히 종료(요약 생략).
3. run_summary_pipeline.py --send 실행
   - 실패 시 알림 후 중단
4. 성공 시 완료 알림(수집 N건 -> 전송 M건, 소요 시간).

운영 알림은 종목 요약과 같은 채널로 가되 '🤖 파이프라인' 접두로 구분한다.

세션 만료 처리:
  - .env에 CAPIQ_EMAIL / CAPIQ_PASSWORD가 있으면 이메일·비밀번호는 자동 입력된다.
  - MFA 4자리 코드는 자동 조회하지 않는다(인증 메일이 Gmail이 아님). 세션 만료 시
    열린 브라우저 창에서 사용자가 직접 MFA를 입력해 로그인을 완료해야 한다.
  - 무인 실행 중 아무도 입력하지 않으면 collect가 타임아웃(exit 2)되고, 이 스크립트가
    "세션 만료" 알림을 보낸다. 이후 사람이 한 번 로그인하면 세션이 다시 유지된다.

Usage:
  python scripts/run_daily_pipeline.py            # 정식 실행
  python scripts/run_daily_pipeline.py --heartbeat  # 신규 0건이어도 완료 알림
  python scripts/run_daily_pipeline.py --notify-test # 알림 경로만 1건 테스트
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime

from summary_lib.config import (
    LOG_DIR,
    ROOT,
    RUNS_DIR,
    SUMMARY_ROOT,
    TelegramSettings,
    load_env_file,
)
from summary_lib.telegram_client import sanitize_telegram_html, send_messages

log = logging.getLogger("pipeline")

PYTHON = sys.executable
COLLECT_SCRIPT = ROOT / "scripts" / "collect_capiq_transcripts.py"
SUMMARY_SCRIPT = ROOT / "scripts" / "run_summary_pipeline.py"
LATEST_RUN = RUNS_DIR / "latest.json"
LATEST_BATCH = SUMMARY_ROOT / "latest_batch.json"


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / f"pipeline_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _send(settings, text: str) -> bool:
    try:
        sent = send_messages(settings, [sanitize_telegram_html(text)])
        return sent > 0
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 파이프라인을 막지 않도록
        log.error("알림 전송 실패: %s", exc)
        return False


def notify_alert(text: str) -> bool:
    """장애/세션만료/실패 알림 → 전용 알림 봇(ALERT_BOT_TOKEN, 미설정 시 요약 봇으로 폴백)."""
    return _send(TelegramSettings.alert_from_env(), text)


def notify_ops(text: str) -> bool:
    """정상 운영 상태(완료·heartbeat) 알림 → 기존 요약 봇."""
    return _send(TelegramSettings.from_env(), text)


def run_step(name: str, args: list[str]) -> int:
    log.info("STEP 시작: %s", name)
    result = subprocess.run([PYTHON, *args], cwd=str(ROOT))
    log.info("STEP 종료: %s (exit %d)", name, result.returncode)
    return result.returncode


def read_json_int(path, key: str) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    value = data.get(key, 0)
    if isinstance(value, dict):  # telegram 블록처럼 중첩된 경우 방어
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main() -> int:
    load_env_file()
    setup_logging()
    started = datetime.now()

    if "--notify-test" in sys.argv:
        ok_alert = notify_alert("🚨 <b>장애 알림 봇 테스트</b>\n장애 알림 전용 봇 경로가 정상 동작합니다.")
        ok_ops = notify_ops("🤖 <b>운영 알림 테스트</b>\n요약 봇(완료·heartbeat) 경로가 정상 동작합니다.")
        log.info("알림 테스트: 장애봇=%s, 요약봇=%s", "성공" if ok_alert else "실패", "성공" if ok_ops else "실패")
        return 0 if (ok_alert and ok_ops) else 1

    heartbeat = "--heartbeat" in sys.argv

    # --- STEP 1: 수집 ---
    code = run_step("수집", [str(COLLECT_SCRIPT)])
    if code == 2:
        notify_alert(
            "⚠️ <b>CapIQ 세션 만료</b>\n"
            "로그인 세션이 만료되어 자동 수집을 못 했습니다.\n"
            "<code>collect_capiq_transcripts.py --setup</code>을 실행한 뒤 열리는 "
            "브라우저 창에서 로그인(이메일·비밀번호·MFA 4자리)을 완료하면 세션이 다시 유지됩니다."
        )
        return 2
    if code != 0:
        notify_alert(f"⚠️ <b>CapIQ 수집 실패</b> (exit {code})\n서버 로그를 확인하세요.")
        return code

    new_count = read_json_int(LATEST_RUN, "download_count")
    log.info("신규 수집 건수: %d", new_count)

    if new_count == 0:
        log.info("신규 transcript 없음. 요약·전송 단계 생략.")
        if heartbeat:
            notify_ops(
                f"🤖 <b>CapIQ 파이프라인</b>\n"
                f"정상 실행. 신규 실적 transcript 없음 ({started:%Y-%m-%d %H:%M})."
            )
        return 0

    # --- STEP 2: 요약 + 전송 ---
    code = run_step("요약·전송", [str(SUMMARY_SCRIPT), "--send"])
    if code != 0:
        notify_alert(
            f"⚠️ <b>요약/전송 실패</b> (exit {code})\n"
            f"수집은 {new_count}건 완료됐으나 요약 단계에서 실패했습니다. 로그를 확인하세요."
        )
        return code

    # --- STEP 3: 완료 알림 (정상 운영 → 요약 봇) ---
    sent = read_json_int(LATEST_BATCH, "summary_count")
    elapsed = (datetime.now() - started).total_seconds()
    notify_ops(
        f"✅ <b>CapIQ 파이프라인 완료</b>\n"
        f"수집 {new_count}건 → 요약·전송 {sent}건 (소요 {elapsed:.0f}초)"
    )
    log.info("파이프라인 완료: 수집 %d, 전송 %d, 소요 %.0fs", new_count, sent, elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
