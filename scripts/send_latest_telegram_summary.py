from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


TELEGRAM_MESSAGE_LIMIT = 3900


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def split_message(text: str, limit: int) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]

    parts = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + limit, len(text))
        if end < len(text):
            split_at = text.rfind("\n\n", cursor, end)
            if split_at <= cursor + limit // 2:
                split_at = text.rfind("\n", cursor, end)
            if split_at <= cursor + limit // 2:
                split_at = end
            end = split_at
        parts.append(text[cursor:end].strip())
        cursor = end
    return [part for part in parts if part]


def sanitize_telegram_html(text: str) -> str:
    escaped = html.escape(text, quote=False)
    return escaped.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def find_latest_summary(root: Path) -> Path:
    summary_root = root / "output" / "summaries" / "grok"
    files = sorted(summary_root.glob("*/*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No summary markdown files found under {summary_root}")
    return files[0]


def split_existing_title(body: str) -> tuple[str, str]:
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("<b>") and lines[0].endswith("</b>"):
        title = lines[0].removeprefix("<b>").removesuffix("</b>").strip()
        rest = "\n".join(lines[1:]).strip()
        return title, rest
    if len(lines) >= 2:
        ticker_match = re.search(r"\b([A-Z]{1,6})\b.*\(([^)]+)\)", lines[0])
        session_match = re.search(r"세션:\s*(.+)", lines[1])
        if ticker_match and session_match:
            title = f"{ticker_match.group(1)} | {session_match.group(1).strip()}"
            rest = "\n".join(lines[2:]).strip()
            return title, rest
    return "", body.strip()


def send_message(token: str, chat_id: str, text: str) -> None:
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API error {exc.code}: {detail}") from exc
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API returned ok=false: {data}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--summary-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    load_env(root / ".env")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first.")

    summary_path = Path(args.summary_file).resolve() if args.summary_file else find_latest_summary(root)
    body = summary_path.read_text(encoding="utf-8").strip()
    title, body = split_existing_title(body)
    header = f"<b>{title}</b>\n\n" if title else ""
    body_limit = max(1000, TELEGRAM_MESSAGE_LIMIT - len(header) - 80)
    parts = split_message(body, body_limit)

    print(f"Summary file: {summary_path}")
    print(f"Telegram messages: {len(parts)}")
    if args.dry_run:
        print("Dry run only.")
        return 0

    for idx, part in enumerate(parts, start=1):
        prefix = f"Part {idx}/{len(parts)}\n\n" if len(parts) > 1 else ""
        message = sanitize_telegram_html(f"{header}{prefix}{part}".strip())
        send_message(token, chat_id, message)
        print(f"Sent {idx}/{len(parts)}: {len(message)} chars")
        time.sleep(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
