"""Grok transcript 요약 -> Telegram 전송 파이프라인 CLI.

telegram_summary.ipynb를 모듈화한 실행 진입점.

Usage:
  python scripts/run_summary_pipeline.py                     # 최근 수집분(latest.json) 요약, 전송은 안 함
  python scripts/run_summary_pipeline.py --send              # 요약 후 Telegram 전송까지
  python scripts/run_summary_pipeline.py --input transcripts/2026-07-10
  python scripts/run_summary_pipeline.py --list-only         # 대상 파일만 확인
  python scripts/run_summary_pipeline.py --force             # 기존 요약이 있어도 다시 요약

기본 입력은 collector가 남긴 output/collection_runs/latest.json이며,
이미 요약 md가 있는 파일은 건너뛴다(--force로 재요약).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

import time

from summary_lib import prompts
from summary_lib.config import (
    LOG_DIR,
    GrokSettings,
    TelegramSettings,
    load_env_file,
)
from summary_lib.outputs import write_batch_outputs
from summary_lib.summarizer import (
    load_summary_result,
    sent_marker_path,
    summarize_file,
    summary_md_path,
)
from summary_lib.telegram_client import build_telegram_messages, send_document, send_messages
from summary_lib.transcript_io import select_input_files

# 일본 기업이지만 미국 기업과 동일하게 단체 채팅방에만 전송할 기업 (JP 방 추가 전송 제외).
# 파일명(회사명) 부분 일치, 소문자 비교.
JP_EXTRA_SEND_EXCLUDE = ("kioxia", "murata")

log = logging.getLogger("summary")


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / f"summary_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize collected transcripts and send to Telegram.")
    parser.add_argument(
        "--input",
        default="latest",
        help="'latest' (기본, 최근 수집분) 또는 transcript 폴더 경로",
    )
    parser.add_argument("--max-files", type=int, default=None, help="최대 처리 파일 수")
    parser.add_argument("--force", action="store_true", help="기존 요약이 있어도 다시 요약")
    parser.add_argument("--send", action="store_true", help="요약 후 Telegram 전송까지 수행")
    parser.add_argument("--list-only", action="store_true", help="대상 파일 목록만 출력하고 종료")
    args = parser.parse_args()

    load_env_file()
    setup_logging()

    files = select_input_files(args.input, prompts.FILE_FORMAT_PREFERENCE)
    if args.max_files:
        files = files[: args.max_files]

    if not files:
        log.info("No input transcript files found (input=%s). Nothing to do.", args.input)
        return 0

    def plan_label(path) -> str:
        md_exists = summary_md_path(path).exists()
        if args.force or not md_exists:
            return "SUMMARIZE"
        if args.send and not sent_marker_path(path).exists():
            return "RESEND (md exists, unsent)"
        return "SKIP (already handled)"

    log.info("Input source: %s | files: %d", args.input, len(files))
    for path in files:
        log.info("  - [%s] %s", plan_label(path), path.name)

    if args.list_only:
        return 0

    grok = GrokSettings.from_env()
    # 비일본 요약 수신자: 기본 채널 + EARNINGS_EXTRA_CHAT_IDS(단체방 등). 복수 지원.
    telegram_targets = TelegramSettings.summary_targets_from_env() if args.send else []
    jp_telegram = TelegramSettings.jp_from_env() if args.send else []  # 미설정이면 빈 리스트

    # 스트리밍 처리: 종목별로 [요약 -> 즉시 전송 -> 전송 마커]를 끝내고 다음으로 넘어간다.
    # 중간에 죽어도 완료된 종목은 이미 전송돼 있고, 재실행은 마커 없는 것만 이어서 처리한다.
    # 한 종목의 실패(요약/전송)는 기록만 하고 다음 종목을 계속한다.
    results: list[dict] = []
    failures: list[str] = []
    summarized_count = 0
    resend_count = 0
    skipped_count = 0
    sent_count = 0
    jp_sent_count = 0

    for idx, path in enumerate(files, start=1):
        md_path = summary_md_path(path)
        marker = sent_marker_path(path)
        try:
            if md_path.exists() and not args.force:
                already_sent = marker.exists()
                if not args.send or already_sent:
                    log.info("[%d/%d] Skip (이미 처리됨): %s", idx, len(files), path.name)
                    skipped_count += 1
                    continue
                log.info("[%d/%d] 미전송 요약 재전송: %s", idx, len(files), path.name)
                result = load_summary_result(path)
                resend_count += 1
            else:
                log.info("[%d/%d] Summarizing %s", idx, len(files), path.name)
                result = summarize_file(grok, path)
                summarized_count += 1
                time.sleep(prompts.REQUEST_PAUSE_SEC)

            if args.send:
                msgs = build_telegram_messages([result])
                # 일본 판정: 거래소 코드가 TSE(도쿄)인 경우만. 숫자 티커 판정은
                # 대만(TSEC)·홍콩(SEHK) 기업을 일본으로 오분류하므로 쓰지 않는다.
                is_jp = str(result.get("exchange", "")).strip() == "TSE"
                jp_excluded = any(
                    name in str(result.get("file_name", "")).lower()
                    for name in JP_EXTRA_SEND_EXCLUDE
                )
                # 일본 기업(숫자 티커)은 일본방에만 보낸다. 단 JP_EXTRA_SEND_EXCLUDE
                # (kioxia, murata)는 미국 기업과 동일하게 Earnings방에만 보낸다.
                # 일본방이 미설정이면 일본 기업도 Earnings방으로 폴백.
                if jp_telegram and is_jp and not jp_excluded:
                    jp_ok = 0
                    for jp in jp_telegram:
                        try:
                            jp_ok += send_messages(jp, msgs)
                        except Exception as exc:  # noqa: BLE001 - 수신자 1명 실패가 나머지를 막지 않도록
                            log.warning("일본 chat %s 전송 실패: %s", jp.chat_id, exc)
                            continue
                        # 일본 기업은 요약 직후 원본 transcript(docx)를 첨부한다.
                        # 첨부 실패는 경고만 (요약은 이미 전송됨).
                        send_document(jp, path, caption=f"📄 원본 transcript · {path.name}")
                    if jp_ok == 0:
                        raise RuntimeError("일본 수신자 전원 전송 실패")
                    jp_sent_count += jp_ok
                else:
                    main_ok = 0
                    for tgt in telegram_targets:
                        try:
                            main_ok += send_messages(tgt, msgs)
                        except Exception as exc:  # noqa: BLE001 - 수신자 1명 실패가 나머지를 막지 않도록
                            log.warning("요약 chat %s 전송 실패: %s", tgt.chat_id, exc)
                    if main_ok == 0:
                        raise RuntimeError("요약 수신자 전원 전송 실패")
                    sent_count += main_ok
                marker.write_text(datetime.now().isoformat(), encoding="utf-8")
                log.info("[%d/%d] 전송 완료: %s", idx, len(files), path.name)
            results.append(result)
        except Exception:  # noqa: BLE001 - 한 종목 실패가 배치 전체를 죽이지 않도록
            log.exception("[%d/%d] 처리 실패: %s", idx, len(files), path.name)
            failures.append(path.name)
            continue

    if not results and not failures:
        log.info("No work to do (skipped: %d). Nothing to send.", skipped_count)
        return 0

    if args.send:
        telegram_status: dict = {
            "sent": True,
            "message_count": sent_count,
            "sent_count": sent_count,
            "jp_sent_count": jp_sent_count,
            "sent_at": datetime.now().isoformat(),
        }
    else:
        messages = build_telegram_messages(results)
        telegram_status = {"sent": False, "message_count": len(messages)}
        log.info("Dry run: %d Telegram message(s) built but not sent. Use --send to send.", len(messages))

    if results:
        json_path, csv_path = write_batch_outputs(results, telegram_status=telegram_status)
        log.info("Batch outputs: %s | %s", json_path, csv_path)
    log.info(
        "Done. summarized=%d resent=%d skipped=%d failed=%d telegram_sent=%s",
        summarized_count, resend_count, skipped_count, len(failures), telegram_status.get("sent"),
    )
    if failures:
        log.error("실패 종목 %d건: %s", len(failures), ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
