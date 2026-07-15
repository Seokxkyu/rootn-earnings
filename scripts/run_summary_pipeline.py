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

from summary_lib import prompts
from summary_lib.config import (
    LOG_DIR,
    GrokSettings,
    TelegramSettings,
    load_env_file,
)
from summary_lib.outputs import write_batch_outputs
from summary_lib.summarizer import summarize_files, summary_md_path
from summary_lib.telegram_client import build_telegram_messages, send_messages
from summary_lib.transcript_io import select_input_files

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

    log.info("Input source: %s | files: %d", args.input, len(files))
    for path in files:
        status = "SKIP (summary exists)" if summary_md_path(path).exists() and not args.force else "SUMMARIZE"
        log.info("  - [%s] %s", status, path.name)

    if args.list_only:
        return 0

    grok = GrokSettings.from_env()
    results, skipped = summarize_files(grok, files, force=args.force)

    if not results:
        log.info("No new summaries were generated (skipped: %d). Nothing to send.", len(skipped))
        return 0

    messages = build_telegram_messages(results)
    telegram_status: dict = {"sent": False, "message_count": len(messages)}

    if args.send:
        telegram = TelegramSettings.from_env()
        jp_telegram = TelegramSettings.jp_from_env()  # 일본 기업 추가 전송 chat (없으면 None)
        sent_count = 0
        jp_sent_count = 0
        # 종목별로 기존 chat에 전송하고, 일본 기업(숫자 티커)은 JP chat에도 추가 전송한다.
        for result in results:
            msgs = build_telegram_messages([result])
            sent_count += send_messages(telegram, msgs)
            is_japan = str(result.get("ticker", "")).strip().isdigit()
            if jp_telegram and is_japan:
                try:
                    jp_sent_count += send_messages(jp_telegram, msgs)
                except Exception as exc:  # noqa: BLE001 - JP 전송 실패가 기존 전송을 막지 않도록
                    log.warning("일본 기업 추가 chat 전송 실패 (%s): %s", result.get("ticker"), exc)
        telegram_status = {
            "sent": True,
            "message_count": len(messages),
            "sent_count": sent_count,
            "jp_sent_count": jp_sent_count,
            "sent_at": datetime.now().isoformat(),
        }
    else:
        log.info("Dry run: %d Telegram message(s) built but not sent. Use --send to send.", len(messages))

    json_path, csv_path = write_batch_outputs(results, telegram_status=telegram_status)
    log.info("Batch outputs: %s | %s", json_path, csv_path)
    log.info(
        "Done. summarized=%d skipped=%d telegram_sent=%s",
        len(results), len(skipped), telegram_status.get("sent"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
