from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .config import LATEST_BATCH_PATH, SUMMARY_ROOT

BATCH_CSV_FIELDS = [
    "file_name",
    "source_file",
    "ticker",
    "quarter",
    "session",
    "model",
    "source_characters",
    "chunk_count",
    "summary_file",
    "summarized_at",
]


def write_batch_outputs(
    results: list[dict],
    *,
    telegram_status: dict | None = None,
    batch_time: datetime | None = None,
) -> tuple[Path, Path]:
    """배치 JSON/CSV를 저장하고 latest_batch.json을 갱신한다."""
    batch_time = batch_time or datetime.now()
    batch_dir = SUMMARY_ROOT / batch_time.strftime("%Y-%m-%d")
    batch_dir.mkdir(parents=True, exist_ok=True)
    stamp = batch_time.strftime("%Y%m%d_%H%M%S")
    json_path = batch_dir / f"summary_batch_{stamp}.json"
    csv_path = batch_dir / f"summary_batch_{stamp}.csv"

    payload = {
        "batch_created_at": batch_time.isoformat(),
        "summary_count": len(results),
        "telegram": telegram_status or {"sent": False, "message_count": 0},
        "summaries": results,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_BATCH_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BATCH_CSV_FIELDS)
        writer.writeheader()
        for row in results:
            writer.writerow({field: row.get(field, "") for field in BATCH_CSV_FIELDS})

    return json_path, csv_path
